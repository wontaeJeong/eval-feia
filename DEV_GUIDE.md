# Development Guide

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Tooling

Use:

- Python 3.10+
- uv
- Typer
- Rich
- requests or httpx
- pytest
- pytest-cov

## Install

```bash
uv sync
```

## Test

```bash
uv run pytest
```

## Run

```bash
uv run eval-feia run --repo . --count 1 --concurrency 1 --opencode-version 1.4.6
```

## JSON mode

```bash
uv run eval-feia run --repo . --count 1 --concurrency 1 --opencode-version 1.4.6 --json
```

## Fake server development

Use the fake server tests to develop without real OpenCode or LLM access.

## Logging

Write run logs under:

```text
results/<batch_id>/runs/<run_id>/
```

## Style

Keep domain logic separate from CLI rendering.

Inject dependencies where possible so tests can mock process and HTTP layers.
