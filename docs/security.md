# Security and limits

Manifest instructions are rendered as inert text. The tool never executes them. Its action reads YAML blobs through GitHub's API; it does not import consumer Python, run install hooks from a consumer checkout, or evaluate PR text in a shell.

The action fetch is limited to 1 MB per YAML file, 10 MB total and 1,000 fragments. A truncated Git tree is an explicit error. API errors and malformed history are errors, not empty success. One oversized item must be shortened or replaced with a runbook link.

The GitHub adapter trusts receipts written by `github-actions[bot]` or repository writers. Human-authored receipts must identify their actual author. A trusted bot may record an authorized editor, after the event handler verifies their permission. The repository is the trust boundary: administrators can change workflows and edit comments.

Do not put credentials, customer data or sensitive command output in actions or receipt evidence. Use links to appropriately protected runbooks and logs. Completion comments inherit the source repository's visibility.

GitHub comments provide durable collaboration history, not immutable compliance storage. Deleting a receipt can affect derived state. For stronger retention requirements, export receipts to your audit system or use the local store under your own backup policy.

The compatibility `legacy promote` command recognizes standard squash and merge PR subjects. New plans do not rely on that heuristic: their scope is the declared head inventory. Cherry-picks, reverts and removed features require explicit retained definitions and retirement decisions.
