# Releasing

Release Please prepares version and changelog changes after successful main CI. Merging the release PR is the publication decision. It creates a versioned GitHub release, which triggers the Publish workflow.

Publish checks that the tag matches package metadata, reruns the full CI workflow and attaches its tested wheel and source distribution to the GitHub release. Existing distributions are never replaced with different bytes. The `v1` Actions tag advances only after GitHub distribution publication succeeds. Do not hand-edit ordinary release versions or upload an untested local wheel.

PyPI publication is enabled separately with repository variable `PYPI_PUBLISHING_ENABLED=true`, after its trusted publisher is configured. It uploads the same tested artifacts with attestations. Until enabled, install the versioned wheel from GitHub Releases; the public action installs its own exact trusted source revision and does not require PyPI.

Repository setup requires:

- The organization's `GV_CI_CROSS_REPO_TOKEN` shared with this repository for Release Please. Its events must trigger release PR CI and publication, which the default workflow token cannot do.
- A PyPI trusted publisher for project `deployment-plan`, owner `gigaverse-app`, repository `deployment-plan`, workflow `release.yml`, environment `pypi`.
- A `pypi` GitHub environment and a `release-automation` environment.
- GitHub Pages configured to publish from Actions for the documentation workflow.

After configuring the trusted publisher, enable the variable and dispatch Publish on the existing version tag. If publication fails, repair the environment or publisher and rerun on that same tag. Do not move an immutable release tag or claim PyPI publication succeeded until the installed distribution is verified.
