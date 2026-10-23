# Migrating the original ledger

The loader accepts the existing list-shaped ledger:

```yaml
- pr: 42
  linear: https://linear.app/example/issue/OPS-123
  owner: platform
  date: 2026-10-01
  followups:
    - id: backfill
      environment: both
      phase: after-deploy
      action: Run and verify the backfill.
```

The public action identity becomes `pr-42/backfill`. `both` expands to staging and production. The original Linear workspace is preserved. Bare issue identifiers remain bare; the tool does not invent a company workspace.

Use `--manifest path/to/pending.yaml` or point the action at its parent directory. New fragments can coexist with the ledger. IDs must remain unique across both formats.

## Preserve existing completion evidence

Before replacing the old promotion workflow, inventory its trusted promotion comments. Import only checked rows whose instructions, phase, environment, PR and action identity exactly match the current definition. Record the original comment URL as evidence. An unchecked row or a missing comment is unknown, not proof of completion.

Historical items without evidence remain unresolved for operator reconciliation. Do not mark a historical baseline completed merely because those PRs merged. Keep old comments until the migrated plan and evidence are verified.

Preview an import from known promotion PRs:

```bash
deployment-plan import-legacy --repo example/service \
  --manifest deployment/followups/pending.yaml --environment production \
  --promotion-pr 100 --promotion-pr 120
```

Add `--apply` to persist the previewed matches. The importer verifies comment authors, links the original evidence, and identifies the importing actor. It does not claim to know who originally checked the box. It skips actions that already have current-revision receipts, so rerunning cannot overwrite a later reopening.

## Consumer policy

Move generic tracking code into this package. Keep application requirements, such as a mandatory client upgrade action, in the consumer. `deployment_plan.legacy` provides the original entry models and loading/rendering API for thin compatibility adapters while consumers migrate.

Publish and validate a package release before changing consumers to its exact version. A rollback can restore the previous workflow; the original manifest and new source-PR receipts should remain intact.
