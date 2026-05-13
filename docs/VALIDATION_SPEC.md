# Validation Specification

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Goal

Determine whether the agent produced a useful AutoGen Teams JSON Component Config.

## Validation stages

### V1. Artifact exists

Check expected output paths.

Default candidates:

- `team.json`
- `autogen_team.json`
- `autogen-team.json`
- files matching `*team*.json`

### V2. JSON parse

The file must be valid JSON.

### V3. Shape check

Expected fields depend on AutoGen version, but the config must clearly describe a team/component setup.

Check for:

- provider/component type
- participants or agents
- model client config
- tools if required
- termination condition
- task-relevant instructions

### V4. Secret scan

Reject hardcoded secrets.

Patterns:

- API keys
- passwords
- tokens
- bearer headers
- private keys

### V5. Task-specific requirements

The config should represent an agent able to:

- search the web
- prepare Knox mail report content
- summarize findings
- draft or send a mail report through a configured mail tool abstraction

Do not require real credential values.

### V6. Load or dry-run

If AutoGen dependency is available, attempt to load the config.

If unavailable, record `autogen_load_ok = null`.

## validation.json

Required fields:

```json
{
  "artifact_found": true,
  "artifact_path": "team.json",
  "json_parse_ok": true,
  "schema_ok": true,
  "autogen_load_ok": null,
  "secret_scan_ok": true,
  "task_requirements_ok": true,
  "validation_passed": true,
  "errors": []
}
```
