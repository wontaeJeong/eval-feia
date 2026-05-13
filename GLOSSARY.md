# Glossary

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Agent trajectory

The sequence of messages, tool calls, subagent activity, todo updates, file changes, and status transitions during one run.

## Batch

A group of evaluation runs launched by one command.

## Run

One isolated evaluation execution.

## Worktree

A Git working directory created for one run.

## Runtime guard

A check that prevents invalid prompt execution.

## Served info

The actual server details reported after `opencode serve` starts.

## CWD mismatch

A mismatch between requested worktree path and served project/cwd path.

## Version mismatch

A mismatch between requested OpenCode version and reported version.

## Idle quiet period

A period with no active parent/child sessions and no recent events.

## Source of truth

The local event and snapshot files written by the harness.
