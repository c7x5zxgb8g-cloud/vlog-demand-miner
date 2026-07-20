from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
REPOSITORY = ROOT.parent
CLI = ROOT / "scripts" / "vdm.py"
SETUP = ROOT / "scripts" / "setup_local_environment.py"
PUBLIC_DOCS = (
    ROOT / "SKILL.md",
    ROOT / "agents" / "openai.yaml",
    ROOT / "references" / "content-experiment-protocol.md",
    ROOT / "references" / "local-environment-setup.md",
)
FORBIDDEN = ("cheat-on-content", "cheat-init", "cheat-seed", "cheat-retro", ".cheat-state")


class PublicInterfaceContractTests(unittest.TestCase):
    def assert_public_text(self, text: str) -> None:
        lowered = text.casefold()
        for value in FORBIDDEN:
            self.assertNotIn(value, lowered)

    def test_public_docs_expose_only_nexttake_actions(self) -> None:
        paths = list(PUBLIC_DOCS)
        repository_readme = REPOSITORY / "README.md"
        if repository_readme.is_file():
            paths.append(repository_readme)
        for path in paths:
            with self.subTest(path=path.name):
                self.assert_public_text(path.read_text(encoding="utf-8"))

    def test_creator_templates_do_not_expose_internal_workflow_commands(self) -> None:
        templates = ROOT / "vendor" / "content-engine" / "templates"
        for path in templates.glob("*.md"):
            with self.subTest(path=path.name):
                self.assert_public_text(path.read_text(encoding="utf-8"))

    def test_cli_help_hides_legacy_engine_parameters(self) -> None:
        commands = (
            [sys.executable, str(CLI), "--help"],
            [sys.executable, str(SETUP), "--help"],
        )
        for command in commands:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assert_public_text(completed.stdout)
            self.assertIn("--douyin-adapter-dir", completed.stdout)

    def test_demo_json_and_studio_do_not_expose_internal_engine(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, str(CLI), "--project", directory, "creator-demo"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertIn("generate_next_draft", result["workflow_stages"])
            self.assertNotIn("native_lifecycle", result)
            self.assert_public_text(completed.stdout)
            self.assert_public_text(Path(result["studio"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
