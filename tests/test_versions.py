"""Unit tests for the marketplace version archive.

The comparator must answer exactly like the server's update.CompareVersions:
a mismatch would let the registry order releases differently than the operator
resolves them, and the server trusts the array order rather than re-sorting.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import versions  # noqa: E402


def manifest(plugin_id, version, min_app_version="", key_id="ed25519:aaaaaaaaaaaaaaaa"):
    doc = {"id": plugin_id, "version": version, "type": "integration", "publisher": "veildawn"}
    if min_app_version:
        doc["min_app_version"] = min_app_version
    if key_id:
        doc["signature"] = {"key_id": key_id, "alg": "ed25519", "value": "AA=="}
    return doc


class CompareVersions(unittest.TestCase):
    def test_matches_server_semantics(self):
        cases = [
            ("1.0.0", "1.0.0", 0),
            ("v1.0.0", "1.0.0", 0),
            ("1.0.0+build", "1.0.0", 0),
            ("1.0.1", "1.0.0", 1),
            ("0.10.0", "0.9.0", 1),
            ("2.0", "2.0.0", 0),
            ("1.0.0", "1.0.0-rc.1", 1),
            ("1.0.0-rc.2", "1.0.0-rc.1", 1),
            ("1.0.0-rc.1", "1.0.0-rc.1.1", -1),
            ("1.0.0-1", "1.0.0-alpha", -1),
            ("1.0.0-alpha", "1.0.0-beta", -1),
            ("1.2.x", "1.2.0", 0),
        ]
        for left, right, want in cases:
            with self.subTest(left=left, right=right):
                self.assertEqual(want, versions.compare_versions(left, right))
                self.assertEqual(-want, versions.compare_versions(right, left))

    def test_sorts_newest_first(self):
        got = versions.sort_newest_first(["1.0.0", "1.3.6", "1.3.10", "0.9.9"])
        self.assertEqual(["1.3.10", "1.3.6", "1.0.0", "0.9.9"], got)


class FloorTiers(unittest.TestCase):
    def test_keeps_newest_per_floor(self):
        entries = [
            {"version": "1.3.6", "min_app_version": "0.19.0"},
            {"version": "1.3.5", "min_app_version": "0.19.0"},
            {"version": "1.3.4", "min_app_version": "0.18.0"},
            {"version": "1.3.2", "min_app_version": "0.17.17"},
            {"version": "1.0.0", "min_app_version": "0.17.0"},
        ]
        kept = versions.floors_to_newest(entries)
        self.assertEqual(
            ["1.3.6", "1.3.4", "1.3.2", "1.0.0"],
            [item["version"] for item in kept],
        )

    def test_drops_releases_the_publisher_rolled_back(self):
        history = {
            version: {"version": version, "min_app_version": ""}
            for version in ("2.1.0", "1.6.14", "1.6.12", "1.4.0")
        }
        kept = versions.drop_superseded(history, "1.6.14")
        self.assertEqual(["1.6.14", "1.6.12", "1.4.0"], versions.sort_newest_first(kept))

    def test_tier_serves_every_server_version_like_the_full_set(self):
        # A floor may repeat or even drop between releases; the tier still has
        # to answer "the newest release this server can run" for every build.
        entries = [
            {"version": "3.0.0", "min_app_version": "0.17.0"},
            {"version": "2.9.0", "min_app_version": "0.18.0"},
            {"version": "2.5.0", "min_app_version": "0.18.0"},
            {"version": "2.0.0", "min_app_version": "0.17.0"},
            {"version": "1.0.0", "min_app_version": "0.16.0"},
        ]
        tier = versions.floors_to_newest(entries)
        for app in ["0.15.0", "0.16.0", "0.16.9", "0.17.0", "0.17.5", "0.18.0", "1.2.0", "9.9.9"]:
            with self.subTest(app=app):
                self.assertEqual(
                    newest_compatible(entries, app),
                    newest_compatible(tier, app),
                )


def newest_compatible(entries, app_version):
    for entry in entries:
        floor = entry.get("min_app_version", "")
        if not floor or versions.compare_versions(app_version, floor) >= 0:
            return entry["version"]
    return ""


class FixtureRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "plugins").mkdir()
        (self.root / "revoke.json").write_text('{"version": 1, "revoked": []}\n', encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, relpath, doc):
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def index(self, entry):
        (self.root / "index.json").write_text(
            json.dumps({"version": 1, "plugins": [entry]}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_write_then_check_round_trips(self):
        self.write("plugins/acme.json", manifest("acme", "2.0.0", "0.19.0"))
        self.write("plugins/acme/versions/1.5.0.json", manifest("acme", "1.5.0", "0.18.0"))
        self.index({"id": "acme", "version": "2.0.0", "type": "integration"})

        versions.cmd_write(self.root)
        entries = json.loads((self.root / "index.json").read_text(encoding="utf-8"))["plugins"][0]
        self.assertEqual(
            [
                {"version": "2.0.0", "min_app_version": "0.19.0"},
                {"version": "1.5.0", "min_app_version": "0.18.0"},
            ],
            entries["versions"],
        )
        versions.cmd_check(self.root)

    def test_check_rejects_a_missing_archive_file(self):
        self.write("plugins/acme.json", manifest("acme", "2.0.0", "0.19.0"))
        self.index({
            "id": "acme", "version": "2.0.0", "type": "integration",
            "versions": [{"version": "2.0.0", "min_app_version": "0.19.0"}],
        })
        versions.cmd_check(self.root)
        # The same index with a second advertised version that has no file.
        self.index({
            "id": "acme", "version": "2.0.0", "type": "integration",
            "versions": [
                {"version": "2.0.0", "min_app_version": "0.19.0"},
                {"version": "1.0.0", "min_app_version": "0.17.0"},
            ],
        })
        with self.assertRaises(SystemExit):
            versions.cmd_check(self.root)

    def test_check_rejects_a_latest_that_does_not_lead(self):
        self.write("plugins/acme.json", manifest("acme", "2.0.0", "0.19.0"))
        self.write("plugins/acme/versions/2.0.0.json", manifest("acme", "2.0.0", "0.19.0"))
        self.write("plugins/acme/versions/3.0.0.json", manifest("acme", "3.0.0", "0.19.0"))
        self.index({
            "id": "acme", "version": "2.0.0", "type": "integration",
            "versions": [{"version": "3.0.0"}, {"version": "2.0.0"}],
        })
        with self.assertRaises(SystemExit):
            versions.cmd_check(self.root)

    def test_check_rejects_a_revoked_version(self):
        self.write("plugins/acme.json", manifest("acme", "2.0.0", "0.19.0"))
        self.write("plugins/acme/versions/2.0.0.json", manifest("acme", "2.0.0", "0.19.0"))
        self.index({
            "id": "acme", "version": "2.0.0", "type": "integration",
            "versions": [{"version": "2.0.0", "min_app_version": "0.19.0"}],
        })
        (self.root / "revoke.json").write_text(
            json.dumps({"version": 1, "revoked": [{"plugin_id": "acme", "version": "2.0.0"}]}),
            encoding="utf-8",
        )
        with self.assertRaises(SystemExit):
            versions.cmd_check(self.root)

    def test_checksum_scoped_revocation_is_refused(self):
        (self.root / "revoke.json").write_text(
            json.dumps({
                "version": 1,
                "revoked": [{"plugin_id": "acme", "checksum": "ab" * 32}],
            }),
            encoding="utf-8",
        )
        with self.assertRaises(SystemExit):
            versions.revoked_matcher(self.root)

    def test_index_shape_omits_an_empty_floor(self):
        self.write("plugins/acme.json", manifest("acme", "1.0.0"))
        self.index({"id": "acme", "version": "1.0.0", "type": "integration"})
        versions.cmd_write(self.root)
        entry = json.loads((self.root / "index.json").read_text(encoding="utf-8"))["plugins"][0]
        self.assertEqual([{"version": "1.0.0"}], entry["versions"])


class IndexSchemaFixtures(unittest.TestCase):
    """The index schema's two lanes, checked with whatever validator CI uses.

    check-jsonschema is installed in CI only, so these run when it is present
    (the tests/fixtures documents are also validated by the workflow directly).
    """

    FIXTURES = Path(__file__).resolve().parent / "fixtures"

    def validate(self, name):
        import json as _json

        from jsonschema import Draft202012Validator

        schema = _json.loads((ROOT / "schemas" / "index-v1.schema.json").read_text(encoding="utf-8"))
        document = _json.loads((self.FIXTURES / name).read_text(encoding="utf-8"))
        return list(Draft202012Validator(schema).iter_errors(document))

    def test_accepts_an_automation_entry(self):
        self.assertEqual([], self.validate("index-automation.json"))

    def test_rejects_an_integration_without_a_provider(self):
        self.assertTrue(self.validate("index-integration-missing-provider.json"))

    def test_rejects_an_automation_without_the_job_capability(self):
        self.assertTrue(self.validate("index-automation-without-job.json"))


if __name__ == "__main__":
    unittest.main()
