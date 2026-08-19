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

- **Qoder / Qoder International** (`qoder`, `qoder-intl`)
- **Kiro / AWS CodeWhisperer** (`kiro`)
- **Cursor** (`cursor`)
- **Google Antigravity** (`antigravity`)
- **Google AI Studio** (`google-ai-studio`)
- **OpenAI OAuth** (`openai`)
- **Anthropic** (`anthropic`)
- **xAI** (`xai`)
- **Kimi** (`kimi`)
- **WorkBuddy** (`workbuddy`)
- **Quota Guard** (`quota-guard`)

## Validation

Verify manifests against schemas and signature integrity:

```bash
make validate
```
