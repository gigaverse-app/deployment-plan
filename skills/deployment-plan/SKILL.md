---
name: deployment-plan
description: Adopt or operate deployment-plan for manual before/during/after deployment actions, persistent per-environment completion and carry-forward across releases.
---

# Deployment plans

Use the repository's installed release and existing manifest location. Read its deployment runbook before changing authoring or workflow conventions.

1. Inspect the current inventory and workflow. Reuse stable action IDs and source PRs; never create a second tracking implementation.
2. Write one YAML fragment per change with `version: 1` and `actions`. Each action specifies ID, source PR, owner, environments, phase and concrete instructions with a completion check. Keep secrets and sensitive output out of manifests.
3. Run `deployment-plan validate --manifest PATH` and render the relevant environment plans. For a release comparison, pass `--base-manifest` so missing definitions cannot disappear unnoticed.
4. Completion requires evidence that the action actually happened. Use `record` with the exact environment, action ID and stable operation ID, or edit the generated checklist. Never infer completion from a merge, a successful deployment, a missing comment or the age of a PR.
5. Preserve completed fragments. Changed instructions need fresh completion. Reopen incorrect completion; retire obsolete actions with evidence. A conflict requires inspecting all receipts before `--reconcile`.
6. For migration, preview `import-legacy` before applying exact checked matches. Unmatched historical work remains unresolved. Preserve original comments as evidence.
7. Integrate through the public pinned action. It reads consumer manifests as data. Never add a checkout or execute PR code in the write-enabled `pull_request_target` job.

Canonical guides: [GitHub integration](../../docs/github.md), [lifecycle](../../docs/lifecycle.md), [migration](../../docs/migration.md), and [security](../../docs/security.md).
