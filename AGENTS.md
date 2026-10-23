# Working on deployment-plan

- Read [contributing](docs/contributing.md) and [the lifecycle contract](docs/lifecycle.md) before changing behavior.
- Keep one canonical action and receipt model. JSON, Markdown and providers must share the same planner.
- Never infer completion from a merge, deployment, missing API data, changed instructions or an unchecked historical row.
- Preserve receipt history and unresolved conflicts. New completion must identify the exact instruction revision and environment.
- Treat consumer repositories as data. Never check out or execute PR code in a workflow with write permissions.
- Add a failing regression before fixing a bug. Exercise the installed wheel and actual CLI for packaging and command changes.
- Use Conventional Commits for every commit and PR title. Verify actual PR titles after edits.
- Follow [releasing](docs/releasing.md); release artifacts must come from successful CI.
