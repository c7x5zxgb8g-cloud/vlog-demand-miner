from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).parents[1] / "scripts" / "asr_whisper_cpp.py"
SPEC = importlib.util.spec_from_file_location("asr_whisper_cpp", MODULE)
assert SPEC and SPEC.loader
ASR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASR)


class WhisperCppAdapterTests(unittest.TestCase):
    def test_parse_srt_preserves_millisecond_back_pointers(self) -> None:
        segments = ASR.parse_srt(
            "1\n00:00:01,250 --> 00:00:03,500\n第一句\n\n"
            "2\n00:01:02,005 --> 00:01:04,020\n第二句\n跨行\n"
        )
        self.assertEqual(segments, [
            {"start_ms": 1250, "end_ms": 3500, "text": "第一句"},
            {"start_ms": 62005, "end_ms": 64020, "text": "第二句 跨行"},
        ])

    def test_parse_srt_rejects_empty_output(self) -> None:
        with self.assertRaisesRegex(ValueError, "srt_segments_required"):
            ASR.parse_srt("\n")


if __name__ == "__main__":
    unittest.main()
