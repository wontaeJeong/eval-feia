# Security

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Threat model

The harness executes AI-generated actions through an agent runtime.

Treat it as arbitrary code execution inside the selected worktree.

## Required controls

### Local bind only

OpenCode server must bind to:

```text
127.0.0.1
```

### Server password

Set:

```text
OPENCODE_SERVER_PASSWORD
```

Use Basic Auth for every request.

### Secret redaction

Never log:

- OPENCODE_SERVER_PASSWORD
- Basic Auth header
- API keys
- tokens
- private keys
- full env dumps

### Per-run isolation

Set per-run:

- `HOME`
- `XDG_CONFIG_HOME`
- `XDG_CACHE_HOME`
- `TMPDIR`

### Cleanup

Kill process groups, not only parent process.

Cleanup by manifest only.

### Output scan

Validation must scan generated files for secrets.

## Non-goals

This MVP does not provide container sandboxing.

Container isolation can be added later.
