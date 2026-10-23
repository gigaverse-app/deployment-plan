"""Pure planning and receipt reduction, shared by every output and provider."""

from deployment_plan.models import Action, Inventory, Item, Plan, Receipt, Status, Transition


def resolve(action: Action, environment: str, receipts: list[Receipt]) -> Item:
    events: dict[str, Receipt] = {}
    for receipt in receipts:
        if (receipt.action_id, receipt.revision, receipt.environment) != (action.id, action.revision, environment):
            continue
        previous = events.get(receipt.operation_id)
        if previous is not None and previous != receipt:
            raise ValueError(f"operation {receipt.operation_id} has conflicting payloads")
        events[receipt.operation_id] = receipt
    referenced: set[str] = set()
    for event in events.values():
        if len(set(event.parents)) != len(event.parents):
            raise ValueError(f"duplicate parents for {event.operation_id}")
        if event.operation_id in event.parents or any(parent not in events for parent in event.parents):
            raise ValueError(f"missing or self-referencing parents for {event.operation_id}")
        referenced.update(event.parents)
    # A cycle must not make every event disappear and falsely yield pending/success.
    remaining = set(events)
    processed: set[str] = set()
    while remaining:
        ready = {key for key in remaining if set(events[key].parents) <= processed}
        if not ready:
            raise ValueError(f"cyclic receipt history for {action.id}")
        processed.update(ready)
        remaining -= ready
    frontier = tuple(sorted(set(events) - referenced))
    status = Status.PENDING
    if len(frontier) > 1:
        status = Status.CONFLICT
    elif frontier:
        status = {
            Transition.COMPLETE: Status.COMPLETE,
            Transition.REOPEN: Status.PENDING,
            Transition.RETIRE: Status.RETIRED,
        }[events[frontier[0]].transition]
    return Item(action=action, environment=environment, status=status, frontier=frontier)


def plan(head: Inventory, environment: str, receipts: list[Receipt], base: Inventory | None = None) -> Plan:
    base = base if base is not None else Inventory()
    result = Plan(environment=environment, errors=[*head.errors, *base.errors])
    previous = {action.id: action for action in base.actions}
    current = {action.id: action for action in head.actions}
    # Missing definitions remain visible. Removal cannot silently discharge an obligation.
    inventory = {**previous, **current}
    for action in inventory.values():
        old = previous.get(action.id)
        removed_environment = (
            environment not in action.environments and old is not None and environment in old.environments
        )
        if removed_environment:
            assert old is not None
            action = old
        if environment not in action.environments:
            continue
        try:
            item = resolve(action, environment, receipts)
        except ValueError as exc:
            result.errors.append(str(exc))
            item = Item(action=action, environment=environment, status=Status.CONFLICT)
        missing = action.id not in current or removed_environment
        if missing and item.status != Status.RETIRED:
            result.errors.append(f"{action.id}: removed definition requires explicit retirement; restore the fragment")
        if item.status == Status.CONFLICT:
            result.errors.append(f"{action.id}: conflicting completion history requires explicit reconciliation")
        result.items.append(item.model_copy(update={"carried": action.id in previous, "missing": missing}))
    order = {"before": 0, "during": 1, "after": 2}
    result.items.sort(key=lambda item: (order[item.action.phase], item.action.id))
    return result
