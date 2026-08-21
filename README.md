# AI Provider Plugins (Marketplace)

Official plugin marketplace and distribution repository for [`ai-proxy-service`](https://github.com/veildawn/ai-proxy-service).

This repository contains signed WebAssembly (Wasm) plugin manifests, marketplace indexes, and JSON schemas for runtime distribution.

## Repository Layout

```text
plugins/<id>.json        Signed distribution manifests (with embedded Wasm / configuration)
schemas/                 Marketplace and plugin v3 JSON schemas
publishers/              Verified publisher public keys
index.json               Marketplace catalog index
revoke.json              Revocation list
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
make validate
```
