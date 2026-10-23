# deployment-plan extraction and adoption

Status: 0.1.1 published on GitHub Releases; consumer adoption CI is in progress. Retire the migration checklist when both consumers use a published release and their integration checks pass.

## Problem and outcome

A release can contain hundreds of PRs. Each PR must leave durable, actionable instructions for operators, and unfinished work must remain visible across staging and production releases. Completion is per environment and instruction revision. Merging a PR or deleting a checklist does not mean an action happened.

The standalone Apache-2.0 Python package will own validation, planning, rendering, persistence and the GitHub integration. Backend and AI own their manifests, environment configuration and business-specific requirements. No private imports or Salesforce dependencies are permitted.

## Contracts

1. One YAML fragment per change is the authoring default. Each action has a stable repository-wide ID, instructions, owner, phases (before/during/after), environments, and optional reference URLs. The legacy backend ledger remains readable with IDs namespaced by originating PR. Definitions are data; commands are never executed.
2. A canonical definition hash covers operational instructions and scope. Completion of a previous revision never completes changed instructions. Cosmetic provenance changes do not reset completion. Staging and production completion are independent.
3. The release head inventory selects eligible work. Unfinished definitions remain in the inventory and appear in every later release. Comparing the base inventory identifies carried work. Missing unfinished definitions are visible migration/removal errors; definitions remain retained even after explicit retirement. A release branch merge is not deployment evidence.
4. Append-only receipts on each originating PR record completion, reopening or retirement, the definition revision, environment, authenticated actor, evidence, timestamp and predecessor. Receipt predecessor IDs define causal order; comment timestamps never choose a winner. Repeated operation IDs are idempotent. Conflicting successors are surfaced, never silently last-write-wins. API failures are errors, never an empty successful plan.
5. A promotion comment is a replaceable view. Stable item metadata identifies the action and revision. Authorized checkbox edits can append receipts; edited descriptions cannot manufacture completion. Explicit CLI completion/reopen supports recovery and audit evidence. Comment size limits require bounded chunks with stable markers.
6. Planning is pure and shared by JSON and Markdown output. The GitHub adapter fetches state and persists receipts. Local SQLite receipts support durable offline use. Strict validation keeps valid entries available with visible diagnostics; invalid input cannot produce a successful empty plan.
7. GitHub workflows run trusted released tool code with least privilege. PR manifests are parsed as data. Untrusted fork code is never executed with a write token. Public actions install the exact package corresponding to their immutable release.

## Delivery sequence

- [x] Extract models/legacy loader and preserve the existing behavioral suite; remove Linear workspace rewriting and private Git/Linear imports.
- [x] Implement canonical definitions, revision hashes, fragments, environment configuration, before/during/after phases, JSON and Markdown planning.
- [x] Implement receipt reduction, idempotency, conflicts, complete/reopen/retire, revision invalidation and carry-forward.
- [x] Implement GitHub API pagination, trusted writers, immutable receipts, checkbox edits, size-bounded projection reconciliation and failure recovery.
- [x] Provide CLI and reusable GitHub Actions/workflows for review, promotion and completion, plus offline commands.
- [x] Add lifecycle integration tests using real temporary Git repositories and a local HTTP transport harness; test the installed wheel separately.
- [x] Publish readable README, quickstart, schema, lifecycle, security model, migration and operator recovery docs, examples and adoption skill.
- [x] Configure sibling-style lint/test/build/docs CI, conventional PR titles, Release Please, tested-artifact PyPI publication and versioned Actions tags.
- [x] Create public repository, verify CI and release packaging, publish first usable release. PyPI account setup is explicitly deferred; GitHub Releases is the tested public distribution channel.
- [ ] Adopt in backend, preserving the ledger and business OpenAPI acknowledgement integration while removing the private generic implementation.
- [ ] Adopt in AI with fragment authoring, PR review, staging/production planning and completion handling.
- [ ] Verify both consumer integrations against the actual installed package and run their required CI checks.

## Migration

Never infer historical completion from merge state. Keep every legacy ledger item and source PR. Read existing trusted promotion comments and import only exact matching checked instructions into receipts with evidence linking the original comment. Unchecked or unmatched items remain explicitly unresolved. Produce an operator-readable inventory for historical reconciliation; do not mark a historical baseline as completed automatically. Old sticky comments can remain as evidence until the new plan is verified.

Backend retains its client-force-update policy, consuming public models through a thin adapter. Generic followup tests move with their implementation; backend retains contract tests for its ledger and OpenAPI policy. AI starts with an empty inventory plus the adoption task itself. CI workflow dependencies must include manifest and tool configuration paths without waking unrelated application suites.

Roll out the package before consumer pins. Preserve old command entry points temporarily as delegating wrappers where needed. Rollback reverts consumer workflow wiring; source manifests and durable receipts remain available. A release must not depend on a private VCS URL or an unpublished package.

## Validation and completion audit

- [x] CLI lifecycle: create -> validate -> plan -> complete staging -> later release -> production still pending -> reopen -> changed instructions pending.
- [x] Historical late entry appears even when its original PR predates the release range.
- [x] Removed definitions, reverts, unsupported source identity, malformed YAML and API outages are visible.
- [x] Concurrent and duplicate receipts, stale checkbox edits, untrusted authors, permission failures and partial projection writes cannot invent success.
- [x] Multi-page inventories/comments and large plans retain every item.
- [x] Legacy backend suite and real ledger parse correctly; generic package imports no private modules.
- [x] Built wheel works outside the source checkout; source/wheel metadata and version agree.
- [ ] Finish both consumer CI runs and trusted event verification. Public CI/docs/release checks pass; PyPI configuration remains owner-deferred.

## What we learn from sfdx-hardis

Use per-environment durable state, explicit recovery, stable action metadata and promotion scope explanations. Do not import its AGPL implementation or Salesforce execution layer. Improve on ID-only completion with instruction revisions, and on release-local retries with retained unfinished inventory. Do not claim exactly-once execution: this tool tracks human obligations and evidence.
