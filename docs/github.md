# GitHub integration

Add this workflow to `.github/workflows/deployment-plan.yml`. Replace `v1` with an immutable release SHA when required by your supply-chain policy.

```yaml
name: Deployment plan
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
  pull_request_target:
    types: [opened, synchronize, reopened, ready_for_review]
  issue_comment:
    types: [edited]
permissions:
  contents: read
  pull-requests: read
concurrency:
  group: deployment-plan-${{ github.event_name == 'pull_request' && 'validate' || 'sync' }}-${{ github.event.pull_request.number || github.event.issue.number }}
  cancel-in-progress: false
jobs:
  validate:
    name: Validate deployment plan
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: gigaverse-app/deployment-plan@v1
        with:
          token: ${{ github.token }}
          mode: validate
  sync:
    name: Sync deployment plan
    if: github.event_name == 'pull_request_target' || (github.event_name == 'issue_comment' && github.event.issue.pull_request)
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      # The pinned tool reads YAML through GitHub APIs. No consumer PR code runs.
      - uses: gigaverse-app/deployment-plan@v1
        with:
          token: ${{ github.token }}
          manifest: deployment/followups
          environments: '{"staging":"staging","production":"production"}'
```

The action installs its own pinned source revision. It reads consumer YAML through the GitHub API and never checks out or runs consumer PR code. This is what makes its use on `pull_request_target` safe. Do not add a checkout or execute scripts from the PR in this job.

`environments` maps target branch names to environment names. A PR to a configured branch receives the complete environment plan. Other PRs receive a review of changed definitions. The default-branch copy of the workflow handles checkbox edits, so merge the integration before testing that event.

The read-only `pull_request` job supplies a check on the PR head, including forks. The trusted `sync` job writes review comments and receipts. Feature reviews compare against the merge base, so branches created before adoption are not mistaken for deletion of newer definitions. Promotion plans compare the complete release head with the target environment branch.

Keep these jobs separate from application tests. Manifest changes should validate and refresh plans without starting unrelated test suites.

## Permissions and completion

The workflow needs repository contents read and pull requests write. It reads PR comments, validates an editor's repository permission, appends source-PR receipts and updates promotion comments. It does not need deployment, package, secret or organization administration permissions.

Only edits by repository writers to workflow-authored plan comments can create receipts. Editing an action's identity or revision is rejected. A stale checklist must be refreshed before its checkbox can change history. Human CLI credentials record their authenticated GitHub account.

Receipts are stored as separate source-PR comments. Avoid editing or deleting them. They are append-only by tool policy, not a tamper-proof external audit log. Repository administrators retain GitHub's normal editing powers.

## Refresh and repair

Rerun the plan job after fixing a definition, API permission or a stale edit. Source-PR receipts survive deleted promotion comments. Large plans are split into bounded comments; stale chunks are removed only after all replacement chunks were written. A partial refresh can temporarily show old and new projections, and rerunning reconciles them.
