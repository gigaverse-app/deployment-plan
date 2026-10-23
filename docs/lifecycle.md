# Completion, carry-forward and recovery

An action ID identifies an obligation across releases. Its revision hashes the instructions, phase and environments. Owner and reference changes preserve completion. Changing the operational definition requires a fresh acknowledgement.

Every receipt records the action, revision, environment, operator, evidence, time, operation ID and predecessor receipts. The latest unambiguous transition determines the state:

| Transition | Result |
|---|---|
| `complete` | The operator reports that the action was performed |
| `reopen` | The action is pending again |
| `retire` | The action is intentionally no longer required; evidence explains why |

Staging completion never completes production. A merged PR never completes an action. The tool does not infer successful execution from a deployment or a commit message.

## Carry-forward

Plans read the complete manifest inventory at the release head, rather than selecting only PR numbers in a release range. That includes old unfinished actions and late additions for old PRs. Passing `--base-manifest` identifies actions carried from the previous inventory and detects removed definitions.

Keep fragments in the inventory, including completed or retired actions. Do not delete definitions as a way of checking them off. The review workflow rejects removals. A reverted feature must retain its action definition and explicitly retire it in the affected environments with an explanation.

## Reopen or retire

```bash
deployment-plan record --repo example/service --environment production \
  --id backfill-display-names --transition reopen \
  --operation-id recheck-123 --evidence 'Verification used the wrong database'
```

Use a stable operation ID when retrying the same command. A retry returns the existing receipt. Reusing the ID for different work fails. Use a new operation ID for a new transition.

## Conflicting updates

Two operators can update the same action concurrently. Both receipts are retained, and the action becomes conflicted. Read their evidence, decide the correct state, then use `record --reconcile` with a new operation ID and evidence explaining the decision. This creates a successor referencing both receipts.

Inspect evidence with `deployment-plan history --id ACTION --environment ENVIRONMENT`, adding `--repo owner/repository` for GitHub history. This lists all recorded revisions, including superseded completion and reopening receipts.

API failures fail the command; they never mean an empty completion history. If a write succeeded but the response was lost, retry with the same operation ID. If a checklist edit fails, refresh it and inspect source-PR receipts before retrying.

This is an obligation tracker. It does not provide exactly-once execution, database migrations, automated rollback or proof that an operator's statement is true.
