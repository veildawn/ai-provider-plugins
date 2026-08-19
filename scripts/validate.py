#!/usr/bin/env python3
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


index = load(ROOT / "index.json")
entries = index["plugins"]
by_id = {entry["id"]: entry for entry in entries}
assert len(by_id) == len(entries), "index.json contains duplicate ids"

files = {path.stem: path for path in (ROOT / "plugins").glob("*.json")}
assert set(files) == set(by_id), f"index/files differ: index-only={sorted(set(by_id)-set(files))}, files-only={sorted(set(files)-set(by_id))}"

publishers = {}
for path in (ROOT / "publishers").glob("*.json"):
    doc = load(path)
    assert doc["handle"] == path.stem, f"{path}: handle does not match filename"
    keys = {}
    for key in doc["keys"]:
        raw = base64.b64decode(key["public_key"], validate=True)
        assert len(raw) == 32, f"{path}: Ed25519 public key must be 32 bytes"
        key_id = "ed25519:" + raw[:8].hex()
        assert key["key_id"] == key_id, f"{path}: key_id does not match public_key"
        keys[key_id] = key
    publishers[doc["handle"]] = keys

for plugin_id, path in files.items():
    manifest = load(path)
    entry = by_id[plugin_id]
    assert manifest["id"] == plugin_id, f"{path}: id does not match filename"
    for field in ("version", "type", "name", "description", "publisher"):
        assert entry[field] == manifest[field], f"{path}: index {field} differs from manifest"
    assert manifest["type"] == "integration", f"{path}: provider market only accepts integrations"
    providers = manifest["provides"].get("providers", [])
    assert providers, f"{path}: integration has no provider"
    assert entry["provider_name"] == providers[0]["name"], f"{path}: provider_name differs"
    assert entry["protocols"] == providers[0].get("protocols", ["openai"]), f"{path}: protocols differ"
    signature = manifest["signature"]
    assert signature["key_id"] in publishers.get(manifest["publisher"], {}), f"{path}: signing key is not published"
    assert entry.get("key_id") == signature["key_id"], f"{path}: index key_id differs"
    modules = {module["id"]: module for module in manifest.get("modules", [])}
    used = set()
    for provider in providers:
        module_id = provider.get("module")
        if module_id:
            assert module_id in modules, f"{path}: provider references missing module {module_id}"
            used.add(module_id)
        for host in provider.get("http", []):
            assert "/" not in host and ":" not in host and host != "*", f"{path}: invalid provider HTTP host {host}"
    for module_id, module in modules.items():
        raw = base64.b64decode(module["data"], validate=True)
        assert raw.startswith(b"\0asm"), f"{path}: {module_id} is not Wasm"
        assert 0 < len(raw) <= 8 << 20, f"{path}: {module_id} exceeds 8 MiB"
        assert hashlib.sha256(raw).hexdigest() == module["sha256"], f"{path}: {module_id} SHA256 mismatch"
    assert set(modules) == used, f"{path}: unused modules {sorted(set(modules)-used)}"

revoke = load(ROOT / "revoke.json")
assert revoke["version"] == 1 and isinstance(revoke["revoked"], list), "invalid revoke.json"
print(f"validated {len(files)} integration manifests")
