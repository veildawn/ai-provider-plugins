#!/usr/bin/env python3
"""Structural validation of the marketplace index, publisher keys, plugin
manifests, and revocations.

Build artifacts (plugins/*.json) are no longer committed to git. When they are
absent — a fresh clone without a signing seed — manifest-level checks are
skipped and only index/publisher/revoke invariants are enforced. `make build`
materializes plugins/ and `make check` then proves the artifacts are
reproducible from source.
"""
import base64
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


index = load(ROOT / "index.json")
entries = index["plugins"]
by_id = {entry["id"]: entry for entry in entries}
assert len(by_id) == len(entries), "index.json contains duplicate ids"

# Module digests recorded in the index let downstream consumers verify fetched
# packages; they must be internally consistent even without local artifacts.
for entry in entries:
    if "module_sha256" in entry:
        assert re.fullmatch(r"[0-9a-f]{64}", entry["module_sha256"]), f"{entry['id']}: bad module_sha256"
        assert isinstance(entry.get("module_bytes"), int) and entry["module_bytes"] > 0, f"{entry['id']}: bad module_bytes"

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

revoke = load(ROOT / "revoke.json")
assert revoke["version"] == 1 and isinstance(revoke["revoked"], list), "invalid revoke.json"
revoked_keys = {item["key_id"] for item in revoke["revoked"]}

files = {path.stem: path for path in (ROOT / "plugins").glob("*.json")}
if not files:
    print("plugins/ absent (build artifacts not committed) — validated index, publishers, revocations")
else:
    assert set(files) == set(by_id), (
        f"index/files differ: index-only={sorted(set(by_id)-set(files))}, "
        f"files-only={sorted(set(files)-set(by_id))}"
    )

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
    # A revoked key must not sign anything still listed in the index.
    assert signature["key_id"] not in revoked_keys, f"{path}: signed with revoked key {signature['key_id']}"
    modules = {module["id"]: module for module in manifest.get("modules", [])}
    used = set()
    for provider in providers:
        module_id = provider.get("module")
        relay = provider.get("relay")
        assert bool(module_id) != bool(relay), f"{path}: provider needs exactly one of module or relay"
        if module_id:
            assert module_id in modules, f"{path}: provider references missing module {module_id}"
            used.add(module_id)
        else:
            # Declarative relay invariants (mirror of relayvm.Parse).
            assert isinstance(relay.get("quota_url"), str) and relay["quota_url"].startswith("/"), \
                f"{path}: relay quota_url must be an absolute path"
            windows = relay.get("windows") or []
            assert windows, f"{path}: relay needs at least one window"
            for window in windows:
                assert window.get("key"), f"{path}: relay window needs a key"
                assert window.get("path") or window.get("percent_of") or window.get("used_percent"), \
                    f"{path}: relay window {window.get('key')} needs path, percent_of, or used_percent"
                if window.get("refill", {}).get("kind") == "cycle":
                    assert window["refill"].get("cycle"), f"{path}: cycle refill needs a cycle name"
        if provider.get("models_url") and not str(provider["models_url"]).startswith("/"):
            raise AssertionError(f"{path}: models_url must be a path")
        for host in provider.get("http", []):
            assert "/" not in host and ":" not in host and host != "*", f"{path}: invalid provider HTTP host {host}"
    for module_id, module in modules.items():
        raw = base64.b64decode(module["data"], validate=True)
        assert raw.startswith(b"\0asm"), f"{path}: {module_id} is not Wasm"
        assert 0 < len(raw) <= 8 << 20, f"{path}: {module_id} exceeds 8 MiB"
        assert hashlib.sha256(raw).hexdigest() == module["sha256"], f"{path}: {module_id} SHA256 mismatch"
    assert set(modules) == used, f"{path}: unused modules {sorted(set(modules)-used)}"
    # Recorded digests must match the artifact actually shipped.
    if "module_sha256" in entry:
        module = modules.get(next(iter(used))) if used else None
        if module:
            assert entry["module_sha256"] == module["sha256"], f"{path}: index module_sha256 is stale"
            assert entry["module_bytes"] == len(base64.b64decode(module["data"])), f"{path}: index module_bytes is stale"
        else:
            assert "module_sha256" not in entry, f"{path}: relay provider must not record a module digest"

print(f"validated {len(files)} integration manifests, {len(revoked_keys)} revoked keys")
