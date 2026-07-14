from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).parents[1] / "scripts" / "vdm.py"


class VdmDemoTests(unittest.TestCase):
    def test_demo_runs_validated_evidence_to_l2_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run([sys.executable, str(CLI), "--project", directory, "demo"], capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["submitted_evidence"], 5)
            artifact = Path(directory) / ".vlog-demand-miner" / "artifacts" / result["artifact"][:2] / f"{result['artifact']}.json"
            cluster = json.loads(artifact.read_text(encoding="utf-8"))["data"]["clusters"][0]
            self.assertEqual(cluster["maturity"], "L2_high_confidence_signal")
            self.assertEqual(cluster["coverage"]["independent_creators"], 3)
            self.assertEqual(cluster["coverage"]["independent_commenters"], 3)
            job_payload = next(json.loads(path.read_text(encoding="utf-8")) for path in (Path(directory) / ".vlog-demand-miner" / "artifacts").glob("*/*.json") if json.loads(path.read_text(encoding="utf-8"))["kind"] == "analysis.model_job")
            job_hash = next(path.stem for path in (Path(directory) / ".vlog-demand-miner" / "artifacts").glob("*/*.json") if json.loads(path.read_text(encoding="utf-8")) == job_payload)
            model_input = subprocess.run([sys.executable, str(CLI), "--project", directory, "model-job-input", "--job-artifact", job_hash], capture_output=True, text=True, check=False)
            self.assertEqual(model_input.returncode, 0, model_input.stderr)
            self.assertNotIn("allowed_sources", model_input.stdout)
            self.assertNotIn("demo-C:", model_input.stdout)


if __name__ == "__main__":
    unittest.main()
