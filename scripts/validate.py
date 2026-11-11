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

integration_count = 0
for plugin_id, path in files.items():
    manifest = load(path)
    entry = by_id[plugin_id]
    assert manifest["id"] == plugin_id, f"{path}: id does not match filename"
    for field in ("version", "type", "name", "description", "publisher"):
        assert entry[field] == manifest[field], f"{path}: index {field} differs from manifest"
    # Two lanes share one index. An integration installs resources for an
    # upstream; an automation declares jobs and no provider. The host infers
    # automation from jobs when a manifest omits the field, so accept that too.
    package_type = manifest.get("type") or (
        "automation" if manifest["provides"].get("jobs") else "integration"
    )
    assert package_type in ("integration", "automation"), f"{path}: unknown package type {package_type}"
    assert entry["type"] == package_type, f"{path}: index type differs from manifest"
    providers = manifest["provides"].get("providers", [])
    if package_type == "integration":
        integration_count += 1
        assert providers, f"{path}: integration has no provider"
        assert entry["provider_name"] == providers[0]["name"], f"{path}: provider_name differs"
        assert entry["protocols"] == providers[0].get("protocols", ["openai"]), f"{path}: protocols differ"
    else:
        assert manifest["provides"].get("jobs"), f"{path}: automation declares no job"
        assert providers == [], f"{path}: automation must not declare a provider"
        assert "job" in entry.get("capabilities", []), f"{path}: automation must advertise the job capability"
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
        assert not (module_id and relay), f"{path}: provider must not declare both module and relay"
        if module_id:
            assert module_id in modules, f"{path}: provider references missing module {module_id}"
            used.add(module_id)
        elif relay:
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
            assert "module_sha256" not in entry, f"{path}: provider without a module must not record a module digest"

RAW_RELEASES_PREFIX = "https://raw.githubusercontent.com/veildawn/ai-provider-plugins/main/releases/"
release_manifests = sorted((ROOT / "releases").glob("*/*.json"))
for rel_path in release_manifests:
    rel_doc = load(rel_path)
    assert set(rel_doc) == {"version", "url", "sha512"}, (
        f"{rel_path}: release manifest must have exact keys version, url, sha512"
    )
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(rel_doc["version"])), f"{rel_path}: bad version"
    url = str(rel_doc["url"])
    assert url.startswith(RAW_RELEASES_PREFIX), (
        f"{rel_path}: url must start with {RAW_RELEASES_PREFIX}"
    )
    assert re.fullmatch(r"[0-9a-f]{128}", str(rel_doc["sha512"])), f"{rel_path}: bad sha512"
    archive_rel = url[len("https://raw.githubusercontent.com/veildawn/ai-provider-plugins/main/"):]
    archive_file = ROOT / archive_rel
    assert archive_file.is_file(), f"{rel_path}: referenced archive {archive_rel} is missing"
    actual_sha512 = hashlib.sha512(archive_file.read_bytes()).hexdigest()
    assert actual_sha512 == rel_doc["sha512"], (
        f"{rel_path}: archive sha512 {actual_sha512} != manifest {rel_doc['sha512']}"
    )

print(
    f"validated {len(files)} manifests ({integration_count} integration, "
    f"{len(files) - integration_count} automation), {len(revoked_keys)} revoked keys, "
    f"{len(release_manifests)} host release manifests"
)
