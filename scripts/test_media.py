"""Offline media verification through the public CLI."""
import subprocess
import json
import sys
import tempfile
import unittest
from pathlib import Path

import testkit


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / "sample.wav"
        testkit.write_wav(self.audio, 3200, rate=16000, tone_frames=0)

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(Path(__file__).with_name("verify_media.py")), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8",
        )

    def test_valid_audio_is_verified_without_external_skill(self):
        result = self.cli("--file", self.audio, "--expect", "0.2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_manifest_paths_are_relative_to_the_manifest(self):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps([{"path": "sample.wav", "expect": 0.2}]))
        result = self.cli("--manifest", manifest)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_nonfinite_expectations_and_missing_streams_are_rejected(self):
        for args in (["--expect", "nan"], ["--expect", "0"], ["--kind", "video"]):
            with self.subTest(args=args):
                result = self.cli("--file", self.audio, *args)
                self.assertNotEqual(result.returncode, 0)

    def test_metadata_only_does_not_claim_decode_passed(self):
        result = self.cli("--file", self.audio, "--metadata-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("decode=NOTRUN", result.stdout)

    def test_truncated_audio_is_not_accepted_as_complete(self):
        self.audio.write_bytes(self.audio.read_bytes()[:70])
        result = self.cli("--file", self.audio)
        self.assertNotEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
