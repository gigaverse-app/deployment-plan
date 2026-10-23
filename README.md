# deployment-plan

[![CI](https://github.com/gigaverse-app/deployment-plan/actions/workflows/ci.yml/badge.svg)](https://github.com/gigaverse-app/deployment-plan/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

Remember what each PR needs before, during and after deployment, even when a release contains hundreds of PRs.

Write deployment actions alongside your code. Generate a plan for each environment. Record completion with evidence and carry unfinished actions into later releases.

```yaml
version: 1
actions:
  - id: backfill-display-names
    source_pr: 42
    owner: platform
    environments: [staging, production]
    phase: after
    instructions: |
      Run the display-name backfill.
      Verify the missing-name count is zero.
```

Put the fragment in `deployment/followups/`. The GitHub Action adds a review comment to its PR, then includes it in staging and production plans. Checking it off in staging leaves production pending. Changing the instructions requires a new acknowledgement.

- **Persistent completion:** receipts live on the originating PR, so deleting a promotion comment does not erase the record.
- **Carry-forward:** unfinished actions remain visible in later releases, including late additions for old PRs.
- **Explicit recovery:** reopen or retire an action with evidence; reconcile concurrent updates without losing either receipt.
- **Portable:** Python CLI, JSON output, local SQLite receipts, GitHub integration, arbitrary environments, and a legacy-ledger loader.

The tool tracks manual obligations. It never executes your instructions or infers completion from a merge.

Start with the [quickstart](docs/index.md), [GitHub workflow](docs/github.md), and [completion lifecycle](docs/lifecycle.md). Install the tested wheel from [GitHub Releases](https://github.com/gigaverse-app/deployment-plan/releases). PyPI publication is pending trusted-publisher configuration.

```bash
deployment-plan validate
deployment-plan plan --environment staging
deployment-plan plan --environment production --format json
```

Migrating the original tracker? See [migration and historical evidence](docs/migration.md). To contribute, read [development setup](docs/contributing.md) and [release conventions](docs/releasing.md).

Built by [Gigaverse](https://github.com/gigaverse-app), alongside [Due](https://github.com/gigaverse-app/due), [pytest-obligation](https://github.com/gigaverse-app/pytest-obligation), [pytest-selective](https://github.com/gigaverse-app/pytest-selective), and [ci-esta](https://github.com/gigaverse-app/ci-esta).
