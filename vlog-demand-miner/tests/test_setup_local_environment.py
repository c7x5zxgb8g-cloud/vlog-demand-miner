from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE = Path(__file__).parents[1] / "scripts" / "setup_local_environment.py"
SPEC = importlib.util.spec_from_file_location("setup_local_environment", MODULE)
assert SPEC and SPEC.loader
SETUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SETUP)


class SetupEnvironmentTests(unittest.TestCase):
    def test_model_spec_is_consistent(self) -> None:
        self.assertEqual(len(SETUP.MODEL_SHA256), 64)
        self.assertGreater(SETUP.MODEL_BYTES, SETUP.CHUNK_BYTES)

    def test_sha256_matches_written_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.bin"
            path.write_bytes(b"vdm")
            self.assertEqual(SETUP.sha256(path), hashlib.sha256(b"vdm").hexdigest())

    def test_service_name_is_project_scoped(self) -> None:
        project = Path("/tmp/vdm-pilot")
        self.assertEqual(f"vlog-demand-miner/{project.name}/commenter-hmac", "vlog-demand-miner/vdm-pilot/commenter-hmac")


if __name__ == "__main__":
    unittest.main()
