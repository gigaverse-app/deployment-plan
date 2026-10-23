# Remember the deployment work attached to each PR

A release can contain hundreds of PRs. Some need a backfill before deployment, a configuration change during rollout, or verification afterward. Write those instructions with the change so the release operator can find them weeks later.

`deployment-plan` collects the actions, records completion separately for each environment, and includes unfinished work in later plans. It never executes the instructions.

## Try it locally

Install the tested wheel from [GitHub Releases](https://github.com/gigaverse-app/deployment-plan/releases):

```bash
uv tool install https://github.com/gigaverse-app/deployment-plan/releases/download/v0.1.0/deployment_plan-0.1.0-py3-none-any.whl
```

PyPI publication is pending trusted-publisher setup. Once enabled, `uv tool install deployment-plan` or `pip install deployment-plan` also works.

Create `deployment/followups/backfill.yaml`:

```yaml
version: 1
actions:
  - id: backfill-display-names
    source_pr: 42
    owner: platform
    environments: [staging, production]
    phase: after
    instructions: |
      Run the display-name backfill from the runbook.
      Verify the missing-name count is zero before closing this action.
    references:
      - https://example.com/runbooks/display-names
```

The stable ID is unique across the repository. Open a draft PR first, then set `source_pr` to its number. Offline use may omit it. Phases are `before`, `during` and `after`; environments are arbitrary identifiers.

```bash
deployment-plan validate
deployment-plan plan --environment staging
deployment-plan record --environment staging --id backfill-display-names \
  --transition complete --actor alice --operation-id staging-run-123 \
  --evidence 'Run 123 completed; missing-name count is zero'
deployment-plan plan --environment production --format json
```

The production action remains pending. Local receipts persist in `.deployment-plan/receipts.sqlite3`. Back up that file if using local mode for real operations. Add `.deployment-plan/` to `.gitignore`; keep receipts out of source commits.

## Connect GitHub

The [GitHub integration](github.md) turns fragments into PR review comments and environment promotion checklists. Checking a box saves a receipt on the originating PR. Later releases read those receipts. The CLI uses the same lifecycle with `--repo owner/repository` and `GH_TOKEN` or `GITHUB_TOKEN`.

Keep completed fragments in the inventory. Their completion remains visible, and changed instructions become pending again. [Completion and recovery](lifecycle.md) explains reopening, retirement, concurrent updates and evidence.
