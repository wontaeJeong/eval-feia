# Security and Safety

## Secrets

`eval-feia` must not manage provider credentials in MVP.

Do not call:

- `PUT /auth/{id}`
- provider OAuth endpoints
- MCP auth endpoints

unless a later explicit requirement adds credential management.

## Server authentication

If opencode server is protected with `OPENCODE_SERVER_PASSWORD`, support HTTP basic auth through environment variables only.

Example config:

```yaml
server:
  username: "opencode"
  password_env: "OPENCODE_SERVER_PASSWORD"
```

Never print password values or Authorization headers.

## Filesystem safety

All generated worktrees should live under the configured `worktree_root`. Cleanup must be manifest-based.

Never recursively delete based on a glob such as `.eval-feia/*` unless each path is validated against the manifest.

## Network safety

Assume opencode may have webfetch capability depending on config. If the evaluation must not use web access, state that explicitly in the prompt and/or worktree-local `opencode.json` permissions.

Recommended disposable-worktree opencode config for no-web evaluations:

```json
{
  "permission": {
    "webfetch": "deny",
    "edit": "allow",
    "bash": "allow"
  }
}
```

Adjust this according to local security requirements.

## Permission prompts

Avoid indefinite hangs. If permissions are not preconfigured and opencode emits a permission request, fail clearly or require explicit config for auto-approval.

## Server lifecycle

Do not call `/instance/dispose` in MVP. The user owns the server process.
