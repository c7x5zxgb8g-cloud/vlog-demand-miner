from __future__ import annotations

import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
VENDOR = ROOT / "vendor" / "content-engine"
EXPECTED_COMMIT = "9c42fe0c932fe81a12f07428492bdf7ae8488f41"
EXPECTED_SKILLS = {
    "calibrate", "initialize", "learn-from", "migrate",
    "persona", "predict", "publish", "recommend",
    "retro", "score", "score-blind", "ideate",
    "shoot", "status", "trends",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


class VendorIntegrityTests(unittest.TestCase):
    def test_complete_skill_and_license_are_preserved(self) -> None:
        self.assertTrue((VENDOR / "ENGINE.md").is_file())
        self.assertTrue((VENDOR / "CHANGELOG.md").is_file())
        self.assertIn("MIT License", (VENDOR / "LICENSE").read_text(encoding="utf-8"))
        skills = {path.parent.name for path in (VENDOR / "skills").glob("*/WORKFLOW.md")}
        self.assertEqual(skills, EXPECTED_SKILLS)
        for directory in ("adapters", "hooks", "migrations", "shared-references", "starter-rubrics", "templates", "tools"):
            self.assertTrue((VENDOR / directory).is_dir(), directory)

    def test_only_nexttake_is_discoverable_as_a_skill(self) -> None:
        descriptors = sorted(path.relative_to(ROOT).as_posix() for path in ROOT.rglob("SKILL.md"))
        self.assertEqual(descriptors, ["SKILL.md"])

    def test_provenance_records_pinned_upstream(self) -> None:
        provenance = (VENDOR / "UPSTREAM.md").read_text(encoding="utf-8")
        repository_line = next(line for line in provenance.splitlines() if line.startswith("- Repository:"))
        self.assertRegex(repository_line, r"https://github\.com/[^/]+/[^\`]+\.git")
        self.assertIn(EXPECTED_COMMIT, provenance)

    def test_vendor_contains_no_generated_or_private_state(self) -> None:
        forbidden_names = {".git", "__pycache__", ".auth", ".auth-xhs", ".auth-linkedin", ".debug", ".nexttake-cache", ".nexttake-secrets.json"}
        offenders = []
        for path in VENDOR.rglob("*"):
            if path.name in forbidden_names or path.suffix == ".pyc":
                offenders.append(str(path.relative_to(VENDOR)))
        self.assertEqual(offenders, [])

    def test_manifest_matches_every_vendored_file(self) -> None:
        manifest = VENDOR / "MANIFEST.sha256"
        entries = {}
        for line in manifest.read_text(encoding="utf-8").splitlines():
            digest, relative = line.split("  ", 1)
            entries[relative.removeprefix("./")] = digest
        files = {
            str(path.relative_to(VENDOR)): sha256(path)
            for path in VENDOR.rglob("*")
            if path.is_file() and path != manifest
        }
        self.assertEqual(entries, files)


if __name__ == "__main__":
    unittest.main()
