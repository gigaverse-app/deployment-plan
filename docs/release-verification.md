# Release and adoption verification

Version 0.1.1 is available as a wheel and source distribution on [GitHub Releases](https://github.com/gigaverse-app/deployment-plan/releases/tag/v0.1.1). [Publish run 40036505270](https://github.com/gigaverse-app/deployment-plan/actions/runs/40036505270) validated the release tag, passed all 132 tests across its Python/OS matrix, built and independently installed the wheel, and uploaded the tested artifacts. The `v1` action tag resolves to release commit `282ef2ecae83a701cf64fa1758160478f035efec`.

Both consumers installed the public wheel using their committed lockfiles. Backend preserved all 188 legacy actions and imported 12 exact checked acknowledgements from historical promotion comments. Independent plan reads confirmed five completed staging actions and seven completed production actions. Unknown completion remains pending. Three free-form checked notes are linked for explicit reconciliation in the backend guide.

Adoption CI and cutover tracking: [backend #5532](https://github.com/gigaverse-app/gigaverse-backend/pull/5532) and [AI #3139](https://github.com/gigaverse-app/gigaverse-ai/pull/3139). Their published-action validation jobs and required CI gates pass: [backend run](https://github.com/gigaverse-app/gigaverse-backend/actions/runs/40037045384) and [AI run](https://github.com/gigaverse-app/gigaverse-ai/actions/runs/40036755964). Both main branches require an approving review before normal merge. Trusted workflow activation remains pending those merges.

Read-only previews used each adoption PR head with the real staging base: backend produced 175 staging actions, including 160 carried forward and five completed, with no validation errors; AI produced its initial cutover action with no errors.

PyPI publication is disabled until the owner configures the trusted publisher. The GitHub distributions and pinned action are independently usable.

## Live completion and carry-forward

The public repository uses its own pinned action. A later PR showed the original completed release verification action. A real checkbox edit reopened it and appended a source-PR receipt; subsequent PRs #6 and #7 showed it pending. After revalidating the published distribution, another checkbox edit completed it again. [The 0.1.1 event run](https://github.com/gigaverse-app/deployment-plan/actions/runs/40036745133) passed, and [the refreshed plan](https://github.com/gigaverse-app/deployment-plan/pull/5#issuecomment-6376265460) retained its carried-forward label. The original receipt, reopening and new completion remain separately readable on source PR #1.

The backend import also demonstrates environment independence against real history: the retained actions from PRs #5445 and #5456 are complete in staging and still pending in production.

The first live reopening exposed a missing base snapshot in checkbox refresh. Two regression cases failed before the fix, covering both carry-forward context and removed-action warnings. The 0.1.1 patch repairs that shared planner call and passed the live completion event above.
