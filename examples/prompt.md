# Evaluation Prompt Example

You are running inside a disposable git worktree prepared by eval-feia.

Rules:

- Do not use web access.
- Inspect the repository locally.
- Make the smallest correct change for the requested task.
- Run relevant local tests if available.
- At the end, summarize:
  - files changed
  - commands run
  - test result
  - remaining risks

Task:

Implement the requested change here.
