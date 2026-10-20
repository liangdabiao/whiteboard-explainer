"""Offline regression tests; no media generation or paid API requests."""
import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import user_gates as gates


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.root / "script.md"
        self.artifact.write_text("reviewed", encoding="utf-8")

    def record(self, gate, artifacts=None, note="用户确认"):
        gates.stage_review(self.root, gate, artifacts or [self.artifact])
        gates.commit_review(self.root, gate, note)

    def approve_through(self, last):
        for gate in gates.GATES[:gates.GATES.index(last) + 1]:
            self.record(gate)

    def test_missing_or_malformed_approval_blocks(self):
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G2")
        (self.root / gates.STATE_FILE).write_text("[]", encoding="utf-8")
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G2")

    def test_staging_records_nothing_and_commit_needs_the_staged_review(self):
        with self.assertRaises(gates.GateError):
            gates.stage_review(self.root, "G3", [self.artifact])
        gates.stage_review(self.root, "G0", [self.artifact])
        self.assertFalse((self.root / gates.STATE_FILE).exists())
        with self.assertRaises(gates.GateError):
            gates.commit_review(self.root, "G0", "   ")
        with self.assertRaises(gates.GateError):
            gates.commit_review(self.root, "G1", "用户确认")
        gates.commit_review(self.root, "G0", "用户确认 G0")
        self.assertIn("G0", gates.load(self.root))

    def test_review_and_commit_never_prompt_the_terminal(self):
        command = [sys.executable, str(Path(gates.__file__).resolve()), "--root", str(self.root)]
        # DEVNULL stdin: any input() call would fail instead of waiting on the user.
        result = subprocess.run(
            command + ["approve", "G0", "--artifact", str(self.artifact)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Review G0", result.stdout)
        self.assertFalse((self.root / gates.STATE_FILE).exists())
        result = subprocess.run(
            command + ["confirm", "G0", "--note", "讲稿确认"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Recorded G0", result.stdout)
        self.assertEqual(gates.load(self.root)["G0"]["note"], "讲稿确认")
        self.assertFalse((self.root / gates.PENDING_FILE).exists())

    def test_artifact_changed_between_review_and_commit_blocks(self):
        gates.stage_review(self.root, "G0", [self.artifact])
        self.artifact.write_text("changed after the user read it", encoding="utf-8")
        with self.assertRaises(gates.GateError):
            gates.commit_review(self.root, "G0", "用户确认")
        self.assertNotIn("G0", gates.load(self.root))

    def test_g0_capability_preflight_binds_declared_capabilities(self):
        review = gates.stage_review(self.root, "G0", [self.artifact],
                             capabilities=["boards", "render"])
        self.assertIn("Pillow", review["capabilities"]["boards"])
        self.assertIn("ffmpeg", review["capabilities"]["render"])
        gates.commit_review(self.root, "G0", "用户确认 G0")
        record = gates.load(self.root)["G0"]
        self.assertEqual(record["capabilities"], review["capabilities"])

    def test_g0_capability_preflight_refuses_missing_credentials(self):
        import os
        empty = self.root / "nohome"
        empty.mkdir()
        with patch.dict(os.environ, {"APIZ_API_KEY": "",
                                     "USERPROFILE": str(empty), "HOME": str(empty)}):
            with self.assertRaises(gates.GateError):
                gates.stage_review(self.root, "G0", [self.artifact], capabilities=["apiz"])
        with self.assertRaises(gates.GateError):
            gates.stage_review(self.root, "G1", [self.artifact], capabilities=["boards"])

    def test_exemption_binds_artifacts_and_lists_the_waived_scope(self):
        gates.exempt(self.root, "G0", [self.artifact],
                     ["任务书无需逐字观看"], "用户说跳过任务书确认")
        record = gates.load(self.root)["G0"]
        self.assertEqual(record["exempted"], ["任务书无需逐字观看"])
        self.assertIn(str(self.artifact.resolve()), record["artifacts"])
        self.assertFalse((self.root / gates.PENDING_FILE).exists())
        gates.require(self.root, "G0")
        with self.assertRaises(gates.GateError):
            gates.exempt(self.root, "G1", [self.artifact], [], "无范围")
        with self.assertRaises(gates.GateError):
            gates.exempt(self.root, "G1", [self.artifact], ["x"], "  ")

    def test_concurrent_staging_is_refused_not_silently_overwritten(self):
        from artifacts import file_lock
        command = [sys.executable, str(Path(gates.__file__).resolve()),
                   "--root", str(self.root)]
        with file_lock(self.root / ".user-gates.lock", "approval"):
            result = subprocess.run(
                command + ["approve", "G0", "--artifact", str(self.artifact)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("producer", result.stderr + result.stdout)

    def test_discard_removes_the_staged_review(self):
        gates.stage_review(self.root, "G0", [self.artifact])
        gates.discard(self.root, "G0")
        with self.assertRaises(gates.GateError):
            gates.commit_review(self.root, "G0", "用户确认")
        self.assertNotIn("G0", gates.load(self.root))

    def test_parent_changed_while_confirmation_waited_cannot_be_overwritten(self):
        self.approve_through("G2")
        gates.stage_review(self.root, "G3", [self.artifact])
        revised = self.root / "revised.md"
        revised.write_text("a different approved script")
        self.record("G2", [revised])
        with self.assertRaises(gates.GateError):
            gates.commit_review(self.root, "G3", "用户确认")
        self.assertNotIn("G3", gates.load(self.root))

    def test_design_changed_after_parsing_cannot_be_approved_with_old_metadata(self):
        self.approve_through("G1")
        material = self.root / "design.json"
        report = {"teaching_plan": [{
            "id": "s01", "role": "rule", "hold": 0, "narration": ["original"],
            "visual": {"form": "text", "objects": ["rule"],
                       "change": "show the rule", "outcome": "the rule is visible",
                       "order": ["rule"]},
        }]}
        material.write_text(json.dumps(report))
        original_read = Path.read_bytes
        changed = []

        def read_then_edit(path):
            data = original_read(path)
            if path == material and not changed:
                report["teaching_plan"][0]["narration"] = ["revised"]
                material.write_text(json.dumps(report))
                changed.append(True)
            return data

        with patch.object(Path, "read_bytes", read_then_edit):
            gates.stage_review(self.root, "G2", [material])
        with self.assertRaises(gates.GateError):
            gates.commit_review(self.root, "G2", "用户确认")
        self.assertEqual(changed, [True])
        self.assertNotIn("G2", gates.load(self.root))

    def test_changed_missing_and_unapproved_inputs_block(self):
        self.approve_through("G3")
        gates.require(self.root, "G3", self.artifact)
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G3", self.root / "other.mp4")
        self.artifact.write_text("changed", encoding="utf-8")
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G3")
        self.artifact.unlink()
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G3")

    def test_reapproval_clears_downstream(self):
        self.approve_through("G3")
        self.record("G2")
        gates.require(self.root, "G2")
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G3")

    def test_referenced_media_changes_block(self):
        image = self.root / "board.png"
        image.write_bytes(b"image")
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({"scenes": [{"image": "board.png"}]}))
        self.record("G0", [plan])
        image.write_bytes(b"different")
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G0")

    def test_preview_is_single_line_and_needs_g2(self):
        with self.assertRaises(gates.GateError):
            gates.authorize_preview(self.root, ["one"])
        self.approve_through("G2")
        with self.assertRaises(gates.GateError):
            gates.authorize_preview(self.root, ["one", "two"])
        with self.assertRaises(gates.GateError):
            gates.authorize_preview(self.root, ["x" * 101])
        gates.authorize_preview(self.root, ["one"])
        self.assertIn("preview", gates.load(self.root))
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G3")

    def test_custom_command_does_not_execute_when_blocked(self):
        marker = self.root / "executed"
        result = subprocess.run(
            [sys.executable, str(Path(gates.__file__).resolve()),
             "--root", str(self.root), "run", "boards", "--",
             sys.executable, "-c", "from pathlib import Path; Path('executed').touch()"],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BLOCKED", result.stderr)
        self.assertFalse(marker.exists())

    def test_shared_narration_function_blocks_before_output(self):
        import build_narration
        with self.assertRaises(gates.GateError):
            asyncio.run(build_narration.build({}, self.root, dry=False))
        self.assertFalse((self.root / "audio").exists())

    def test_render_blocks_before_creating_output(self):
        plan = self.root / "plan.json"
        plan.write_text('{"scenes": []}', encoding="utf-8")
        script = Path(gates.__file__).with_name("render_explainer.py")
        for flags in ([], ["--only", "s01"]):
            result = subprocess.run(
                [sys.executable, str(script), str(plan), "--out", "out/video.mp4", *flags],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("BLOCKED", result.stderr)
        self.assertFalse((self.root / "out").exists())

    def test_approved_custom_command_runs(self):
        self.approve_through("G2")
        result = subprocess.run(
            [sys.executable, str(Path(gates.__file__).resolve()),
             "--root", str(self.root), "run", "boards", "--",
             sys.executable, "-c", "print('ALLOWED')"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ALLOWED", result.stdout)

    def test_narration_spec_must_match_approved_file(self):
        self.approve_through("G2")
        spec = self.root / "plan.build.json"
        spec.write_text('{"voice": "selected", "scenes": []}', encoding="utf-8")
        self.record("G3", [spec])
        gates.require_spec(self.root, {"voice": "selected", "scenes": []})
        with self.assertRaises(gates.GateError):
            gates.require_spec(self.root, {"voice": "different", "scenes": []})

    def test_fast_tts_blocks_before_deleting_cached_audio(self):
        spec = self.root / "plan.build.json"
        spec.write_text('{"scenes": []}', encoding="utf-8")
        audio = self.root / "audio/narration/parts"
        audio.mkdir(parents=True)
        clip = audio / "cached.mp3"
        clip.write_bytes(b"small")
        script = Path(gates.__file__).with_name("build_narration_fast.py")
        result = subprocess.run([sys.executable, str(script), str(spec)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BLOCKED", result.stderr)
        self.assertEqual(clip.read_bytes(), b"small")

    def test_dry_run_does_not_require_approval_or_write(self):
        spec = self.root / "plan.build.json"
        spec.write_text('{"scenes": []}', encoding="utf-8")
        script = Path(gates.__file__).with_name("build_narration_fast.py")
        result = subprocess.run([sys.executable, str(script), str(spec), "--dry-run"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "audio").exists())
        self.assertFalse((self.root / gates.STATE_FILE).exists())

    def test_other_production_entries_block_without_outputs(self):
        scripts = Path(gates.__file__).parent
        spec = self.root / "boards.json"
        spec.write_text('{"scenes": []}', encoding="utf-8")
        output = self.root / "generated"
        commands = [
            ["gen_board_images.py", str(spec), "--out-dir", str(output)],
            ["gen_tts.py", str(self.root / "narration.yaml"), "--out-dir", str(output)],
            ["make_text_layer.py", "blank:10x10", "--out", str(output / "board.png"),
             "--project-root", str(self.root)],
        ]
        for script, *args in commands:
            with self.subTest(script=script):
                result = subprocess.run([sys.executable, str(scripts / script), *args],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("BLOCKED", result.stderr)
                self.assertFalse(output.exists())

    def test_fast_rate_override_requires_new_approval(self):
        self.approve_through("G2")
        spec = self.root / "plan.build.json"
        spec.write_text('{"scenes": [], "rate": "+22%"}', encoding="utf-8")
        self.record("G3", [spec])
        script = Path(gates.__file__).with_name("build_narration_fast.py")
        result = subprocess.run(
            [sys.executable, str(script), str(spec), "--rate=+15%"],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BLOCKED: --rate", result.stderr)
        self.assertFalse((self.root / "audio").exists())


if __name__ == "__main__":
    unittest.main()
