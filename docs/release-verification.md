# Release and adoption verification

Version 0.1.0 is available as a wheel and source distribution on [GitHub Releases](https://github.com/gigaverse-app/deployment-plan/releases/tag/v0.1.0). [Publish run 40035141389](https://github.com/gigaverse-app/deployment-plan/actions/runs/40035141389) validated the release tag, passed all 130 tests across its Python/OS matrix, built and independently installed the wheel, and uploaded the tested artifacts. The `v1` action tag resolves to release commit `cee9f8d3bf61fcf77f4120f031491a5dcfd9f1b7`.

Both consumers installed the public wheel using their committed lockfiles. Backend preserved all 188 legacy actions and imported 12 exact checked acknowledgements from historical promotion comments. Independent plan reads confirmed five completed staging actions and seven completed production actions. Unknown completion remains pending. Three free-form checked notes are linked for explicit reconciliation in the backend guide.

Adoption CI and cutover tracking: [backend #5532](https://github.com/gigaverse-app/gigaverse-backend/pull/5532) and [AI #3139](https://github.com/gigaverse-app/gigaverse-ai/pull/3139). Their published-action validation jobs pass. Broader consumer CI and post-merge trusted events are still being verified.

PyPI publication is disabled until the owner configures the trusted publisher. The GitHub distributions and pinned action are independently usable.
