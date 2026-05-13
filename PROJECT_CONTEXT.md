# Project Context

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Product name

The product is `eval-feia`.

The meaning is:

> OpenCode Agent Evaluation Harness for measuring autonomous coding-agent trajectories and outputs.

## Core purpose

The app benchmarks how different LLM-backed OpenCode agents perform the same coding task. The result is not only the final file created by the agent. The harness must also quantify the full execution trajectory.

The main evaluation question is:

> Given the same prompt, same repository snapshot, same OpenCode version, and same harness settings, how does each agent behave and what quality of AutoGen Teams config does it produce?

## Target benchmark task

The default task is:

> 웹 검색 후 Knox 메일 리포트 에이전트 작성

The expected output is an AutoGen Teams JSON Component Config that can be parsed, loaded, and validated.

## Why trajectory matters

Two agents may both produce a syntactically valid config. Their trajectories can still differ.

The harness must quantify:

- number of messages
- number of tool calls
- number of subagent sessions
- todo progression
- retry behavior
- validation retry/failure count
- runtime duration
- idle timing
- server restarts
- runtime guard failures
- final validation status

## Hard assumption for this pack

This pack assumes the project starts from zero.

Do not assume an existing implementation. Build the package, CLI, runner, OpenCode integration, logging, metrics, validation, tests, and documentation from scratch.
