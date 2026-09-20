#!/usr/bin/env python3
"""Publish every installable release of a plugin, not just the newest one.

A server picks the newest marketplace release its own build can run: it walks
the index entry's ``versions`` array and takes the first entry whose
``min_app_version`` floor it meets. That only answers "the newest version this
server can install" while the array — and the package behind it — exist:

    index.json  plugins[].versions = [{"version", "min_app_version"}, ...]
    plugins/<id>/versions/<version>.json   exact signed bytes per version
    plugins/<id>.json                      the latest release, unchanged

``versions`` is newest first and always leads with the entry's own ``version``.
Archived files are append-only: a server mid-install fetches one by version, so
a removed file is a broken URL, not a smaller repository.

Three modes:

  --check     (default) prove the index and the archive agree.
  --write     rebuild every entry's ``versions`` array from the files on disk.
  --backfill  materialize archive files from this repo's git history, keeping
              the newest published version per distinct ``min_app_version``
              floor, then write. That subset is sufficient rather than a
              sample: for any server version, the newest compatible release is
              the newest release carrying the highest floor that version
              meets, and that release is the newest of its floor class.

A version named by revoke.json is never archived or listed. Revocations scoped
by ``checksum`` cannot be evaluated offline (the checksum covers the host's
canonical encoding) and are refused here rather than guessed at; scope them by
version or key_id instead.
"""
import argparse
import functools
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def load(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_version(value):
    """Mirrors update.CompareVersions' parse: three numeric parts, a hyphen
    starts the prerelease, and a part that is not a number ends the numeric
    prefix ("1.2.x" is 1.2.0)."""
    text = str(value).strip()
    if text.startswith("v"):
        text = text[1:]
    text, _, _ = text.partition("+")
    base, _, prerelease = text.partition("-")
    nums = [0, 0, 0]
    for i, part in enumerate(base.split(".")[:3]):
        if not part.isascii() or not part.isdigit():
            break
        nums[i] = int(part)
    return nums, prerelease


def _numeric_identifier(value):
    if value and value.isascii() and value.isdigit():
        return value.lstrip("0") or "0", True
    return "", False


def _compare_prerelease(left, right):
    left_parts, right_parts = left.split("."), right.split(".")
    for a, b in zip(left_parts, right_parts):
        if a == b:
            continue
        au, a_numeric = _numeric_identifier(a)
        bu, b_numeric = _numeric_identifier(b)
        if a_numeric and b_numeric:
            if len(au) < len(bu) or (len(au) == len(bu) and au < bu):
                return -1
            return 1
        if a_numeric:
            return -1
        if b_numeric:
            return 1
        return -1 if a < b else 1
    if len(left_parts) < len(right_parts):
        return -1
    if len(left_parts) > len(right_parts):
        return 1
    return 0


def compare_versions(left, right):
    """Same answer as update.CompareVersions: -1, 0, or 1."""
    left_nums, left_pre = _parse_version(left)
    right_nums, right_pre = _parse_version(right)
    for i in range(3):
        if left_nums[i] != right_nums[i]:
            return -1 if left_nums[i] < right_nums[i] else 1
    if left_pre == right_pre:
        return 0
    if left_pre == "":
        return 1
    if right_pre == "":
        return -1
    return _compare_prerelease(left_pre, right_pre)


def _version_of(item):
    return item["version"] if isinstance(item, dict) else str(item)


def sort_newest_first(items):
    """Sort dicts-or-strings newest first, matching update.CompareVersions."""
    return sorted(
        items,
        key=functools.cmp_to_key(
            lambda a, b: compare_versions(_version_of(b), _version_of(a))
        ),
    )


def floors_to_newest(entries):
    """Keep the newest entry per distinct min_app_version floor.

    ``entries`` is newest first. For any server version, the newest release it
    can run belongs to the highest floor it meets, and this keeps that floor's
    newest member — so nothing reachable is dropped.
    """
    seen = set()
    kept = []
    for entry in entries:
        floor = entry.get("min_app_version", "")
        if floor in seen:
            continue
        seen.add(floor)
        kept.append(entry)
    return kept


def drop_superseded(history, latest_version):
    """Drop releases the publisher rolled back.

    A higher version that history remembers but the index no longer leads with
    (workbuddy 2.0.0, antigravity 2.1.0, cursor 2.0.0, ...) was withdrawn.
    Whoever pulls the marketplace gets the version the index leads with, so
    those are exactly the releases nobody may install.
    """
    return {
        version: item
        for version, item in history.items()
        if compare_versions(version, latest_version) <= 0
    }


def version_entry(version, min_app_version):
    """Archive-side shape: the floor is always present, possibly empty."""
    return {"version": version, "min_app_version": min_app_version}


def index_entry(item):
    """Index-side shape: an empty floor is omitted, like min_app_version in a
    manifest and VersionEntry in the server, where absent means "any build"."""
    out = {"version": item["version"]}
    if item.get("min_app_version"):
        out["min_app_version"] = item["min_app_version"]
    return out


def archive_dir(root, plugin_id):
    return root / "plugins" / plugin_id / "versions"


def read_manifest(path):
    doc = load(path)
    version = str(doc.get("version") or "").strip()
    min_app_version = str(doc.get("min_app_version") or "").strip()
    if not VERSION_RE.match(version):
        raise SystemExit(f"{path}: version {version!r} is not a usable version string")
    return version, min_app_version


def archived_entries(root, plugin_id):
    """{version: entry} for the files already materialized under versions/."""
    out = {}
    directory = archive_dir(root, plugin_id)
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        version, min_app_version = read_manifest(path)
        if version != path.stem:
            raise SystemExit(f"{path}: declares version {version}, filename says {path.stem}")
        if version in out:
            raise SystemExit(f"{path}: {version} is archived twice")
        out[version] = version_entry(version, min_app_version)
    return out


def published_entries(root, plugin_id):
    """Every version the registry serves, newest first.

    The latest release lives at plugins/<id>.json; the rest under versions/.
    """
    latest_path = root / "plugins" / f"{plugin_id}.json"
    entries = dict(archived_entries(root, plugin_id))
    if latest_path.is_file():
        version, min_app_version = read_manifest(latest_path)
        entries[version] = version_entry(version, min_app_version)
    return [index_entry(item) for item in sort_newest_first(entries.values())]


def revoked_matcher(root):
    """Returns f(plugin_id, version, key_id). Fails on checksum-scoped entries,
    which cannot be evaluated without the host's canonical encoding."""
    path = root / "revoke.json"
    if not path.is_file():
        return lambda *_: False
    doc = load(path)
    revoked = doc.get("revoked") or []
    for item in revoked:
        if item.get("checksum"):
            raise SystemExit(
                "revoke.json scopes a revocation by checksum, which cannot be evaluated "
                "offline; revoke by plugin_id/version or key_id instead"
            )

    def matches(plugin_id, version, key_id):
        for item in revoked:
            item_plugin = str(item.get("plugin_id") or "").strip()
            item_version = str(item.get("version") or "").strip()
            item_key = str(item.get("key_id") or "").strip().lower()
            if item_plugin and item_plugin != plugin_id:
                continue
            if item_version and item_version != version:
                continue
            if item_key and item_key != key_id:
                continue
            if item_plugin or item_key:
                return True
        return False

    return matches


def signature_key_id(manifest_path):
    if not manifest_path.is_file():
        return ""
    doc = load(manifest_path)
    signature = doc.get("signature") or {}
    return str(signature.get("key_id") or "").strip().lower()


def expected_index_versions(root, plugin_id):
    return published_entries(root, plugin_id)


def cmd_write(root):
    index = load(root / "index.json")
    for entry in index["plugins"]:
        entries = expected_index_versions(root, entry["id"])
        if not entries:
            raise SystemExit(f"{entry['id']}: no package on disk to advertise")
        latest = entries[0]
        if latest["version"] != entry["version"]:
            raise SystemExit(
                f"{entry['id']}: plugins/{entry['id']}.json is {latest['version']} "
                f"but the index says {entry['version']}; publish the built manifest first"
            )
        entry["versions"] = entries
    dump(root / "index.json", index)
    total = sum(len(entry["versions"]) for entry in index["plugins"])
    print(f"wrote versions for {len(index['plugins'])} plugins ({total} releases)")


def cmd_check(root):
    index = load(root / "index.json")
    revoked = revoked_matcher(root)
    problems = []
    total = 0
    for entry in index["plugins"]:
        plugin_id = entry["id"]
        latest_path = root / "plugins" / f"{plugin_id}.json"
        key_id = signature_key_id(latest_path)
        if not latest_path.is_file():
            problems.append(f"{plugin_id}: plugins/{plugin_id}.json is missing")
            continue
        latest_version, _ = read_manifest(latest_path)
        if latest_version != entry["version"]:
            problems.append(
                f"{plugin_id}: latest manifest is {latest_version}, index says {entry['version']}"
            )
        listed = entry.get("versions")
        if not isinstance(listed, list) or not listed:
            problems.append(f"{plugin_id}: index entry has no versions array")
            continue
        expected = expected_index_versions(root, plugin_id)
        if listed != expected:
            problems.append(
                f"{plugin_id}: versions array does not match the archive "
                f"(index {[item.get('version') for item in listed]}, "
                f"archive {[item['version'] for item in expected]})"
            )
        seen = set()
        for item in listed:
            version = str(item.get("version") or "").strip()
            if version in seen:
                problems.append(f"{plugin_id}: {version} is listed twice")
            seen.add(version)
            if revoked:
                item_key = signature_key_id(
                    root / "plugins" / plugin_id / "versions" / f"{version}.json"
                )
                if revoked(plugin_id, version, item_key):
                    problems.append(f"{plugin_id}@{version}: listed while revoked")
        if listed and listed[0].get("version") != entry["version"]:
            problems.append(f"{plugin_id}: versions must lead with the latest release")
        total += len(listed)
    if problems:
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        raise SystemExit(f"marketplace versions check failed with {len(problems)} problem(s)")
    print(f"validated {total} archived releases across {len(index['plugins'])} plugins")


def git_published_entries(root, plugin_id):
    """{version: (entry, raw bytes)} from history, newest commit per version."""
    path = f"plugins/{plugin_id}.json"
    log = subprocess.run(
        ["git", "log", "--format=%H", "--", path],
        cwd=root, capture_output=True, text=True,
    )
    if log.returncode != 0:
        raise SystemExit(f"{plugin_id}: git log failed: {log.stderr.strip()}")
    out = {}
    for commit in log.stdout.split():
        blob = subprocess.run(
            ["git", "show", f"{commit}:{path}"], cwd=root, capture_output=True,
        )
        if blob.returncode != 0:
            continue
        try:
            doc = json.loads(blob.stdout)
        except json.JSONDecodeError:
            continue
        version = str(doc.get("version") or "").strip()
        if not version or version in out:
            continue
        out[version] = (
            version_entry(version, str(doc.get("min_app_version") or "").strip()),
            blob.stdout,
        )
    return out


def cmd_backfill(root):
    index = load(root / "index.json")
    revoked = revoked_matcher(root)
    written = 0
    for entry in index["plugins"]:
        plugin_id = entry["id"]
        latest_path = root / "plugins" / f"{plugin_id}.json"
        if not latest_path.is_file():
            raise SystemExit(f"{plugin_id}: build plugins/{plugin_id}.json before backfilling")
        latest_version, latest_floor = read_manifest(latest_path)
        history = git_published_entries(root, plugin_id)
        history.pop(latest_version, None)
        history = drop_superseded(history, latest_version)
        candidates = [version_entry(latest_version, latest_floor)]
        candidates.extend(item for item, _ in history.values())
        keep = {item["version"]: item for item in floors_to_newest(sort_newest_first(candidates))}
        for version in keep:
            path = archive_dir(root, plugin_id) / f"{version}.json"
            if path.exists():
                continue
            if version == latest_version:
                raw = latest_path.read_bytes()
            else:
                raw = history[version][1]
            key_id = str((json.loads(raw).get("signature") or {}).get("key_id") or "").strip().lower()
            if revoked(plugin_id, version, key_id):
                print(f"skipped {plugin_id}@{version}: revoked")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw if raw.endswith(b"\n") else raw + b"\n")
            written += 1
            print(f"archived {plugin_id}@{version}")
    print(f"backfilled {written} release files")
    cmd_write(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="prove the index and archive agree (default)")
    parser.add_argument("--write", action="store_true", help="rebuild the index versions arrays")
    parser.add_argument("--backfill", action="store_true", help="archive history, then write")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    args = parser.parse_args()
    root = args.root.resolve()
    if sum([args.check, args.write, args.backfill]) > 1:
        raise SystemExit("choose one of --check, --write, --backfill")
    if args.backfill:
        cmd_backfill(root)
    elif args.write:
        cmd_write(root)
    else:
        cmd_check(root)


if __name__ == "__main__":
    main()
