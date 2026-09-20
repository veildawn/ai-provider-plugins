# AI Provider Plugins (Marketplace)

Official plugin marketplace and distribution repository for [`ai-proxy-service`](https://github.com/veildawn/ai-proxy-service).

This repository contains signed WebAssembly (Wasm) plugin manifests, marketplace indexes, and JSON schemas for runtime distribution.

## Repository Layout

```text
plugins/<id>.json                  The latest signed manifest for a plugin
plugins/<id>/versions/<version>.json  Every archived signed release
schemas/                           Marketplace and plugin v3 JSON schemas
publishers/                        Verified publisher public keys
index.json                         Marketplace catalog index
revoke.json                        Revocation list
scripts/versions.py                Maintains the release archive and the index
```

## Releases and the `versions` array

A server installs the newest release *its own build* can run, so the index
advertises more than the latest version:

```json
{
  "id": "openai",
  "version": "1.3.6",
  "min_app_version": "0.19.0",
  "versions": [
    { "version": "1.3.6", "min_app_version": "0.19.0" },
    { "version": "1.3.4", "min_app_version": "0.18.0" },
    { "version": "1.3.2", "min_app_version": "0.17.17" }
  ]
}
```

`versions` is newest first and always leads with the entry's own `version`;
each entry is fetched from `plugins/<id>/versions/<version>.json`. Every
archived file carries its full embedded module, so the archive is hundreds of
megabytes; a server downloads only the single release it installs. The archive
is append-only — a server mid-install downloads one file by version, so a
removed file is a broken URL rather than a smaller repository. Archived
releases span several manifest generations (older packages declare the
`wasm@1` runtime), which is why only the latest manifest of each plugin is
validated against the current manifest schema; every archived manifest still
has to carry a valid publisher signature.

```bash
python3 scripts/versions.py            # check the index against the archive
python3 scripts/versions.py --write    # rebuild the versions arrays
python3 scripts/versions.py --backfill # archive history, newest release per min_app_version floor, then write
```

## Supported Provider Integrations

Requires [`ai-proxy-service`](https://github.com/veildawn/ai-proxy-service) **0.17.0+** (`min_app_version`).

- **Qoder CN / International** (`qoder`, `qoder-intl`)
- **Kiro / AWS CodeWhisperer** (`kiro`)
- **Cursor** (`cursor`)
- **Google Antigravity** (`antigravity`)
- **DeepSeek** (`deepseek`)
- **xAI** (`xai`)
- **Kimi** (`kimi`)
- **WorkBuddy** (`workbuddy`)
- **Volcengine Ark Plans** (`ark`)
- **Qianwen Token Plan** (`qianwen`)
- **StepFun Step Plan** (`stepfun`)
- **MiMo Token Plan** (`mimo`)
- **MiniMax Token Plan** (`minimax`)
- **GLM Coding Plan** (`glm`)
- **OpenCode Go / Zen** (`opencode-go`, `opencode`)

## Validation

Verify manifests against schemas and signature integrity:

```bash
make check
```

`make check` runs `scripts/validate.py`, `scripts/versions.py --check`,
`scripts/verify_signatures.go` (over the latest release and every archived
one), and the unit tests in `tests/`.
