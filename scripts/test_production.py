"""Production CLI regression tests; all synthesis stays offline."""
from __future__ import annotations

import json
import contextlib
import importlib
import io
import subprocess
import sys
import tempfile
import unittest
import hashlib
import asyncio
import copy
import os
from pathlib import Path
from unittest.mock import patch

from PIL import Image


import testkit

SCRIPTS = testkit.SCRIPTS


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.root = testkit.temp_project(self)
        self.spec = {
            "voice": "zh-CN-XiaoyiNeural",
            "rate": "+15%",
            "scenes": [{
                "id": "s01", "image": "board.png",
                "regions": [{"box": [0, 0, 1000, 1000], "annotation": "a_b"}],
            }],
        }
        self.path = self.root / "plan.build.json"
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.spec), encoding="utf-8")

    cli = staticmethod(testkit.cli)

    def test_dry_run_reports_effective_config_without_production_outputs(self):
        result = self.cli("build_narration.py", self.path, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["config"]["voice"], "zh-CN-XiaoyiNeural")
        self.assertEqual(report["config"]["rate"], "+15%")
        self.assertEqual(report["config"]["text_version"], 2)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse((self.root / "audio").exists())
        self.assertFalse((self.root / "plan.json").exists())

    def test_invalid_box_is_rejected_before_any_production(self):
        self.spec["scenes"][0]["regions"][0]["box"] = [0, 900, 1000, 100]
        self.save()
        result = self.cli("build_narration.py", self.path, "--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("s01", result.stderr)
        self.assertIn("box", result.stderr)
        self.assertFalse((self.root / "audio").exists())

    def test_asset_paths_outside_the_project_are_rejected(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Image.new("RGB", (4, 4), "white").save(Path(outside.name) / "outside.png")
        for value in ("../" + Path(outside.name).name + "/outside.png",
                      str((Path(outside.name) / "outside.png").resolve())):
            with self.subTest(value=value):
                self.spec["scenes"][0]["image"] = value
                self.save()
                result = self.cli("build_narration.py", self.path, "--dry-run")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("inside", result.stderr)
        self.spec["scenes"][0]["image"] = "board.png"
        self.spec["font"] = str((Path(outside.name) / "outside.png").resolve())
        self.save()
        result = self.cli("build_narration.py", self.path, "--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inside", result.stderr)

    def test_fast_and_scene_clis_share_inspection_and_validate_fonts(self):
        result = self.cli("build_narration_fast.py", self.path, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["config"]["rate"], "+15%")
        self.spec["scenes"] = [{"id": "s01", "text": "a_b"}]
        self.save()
        result = self.cli("gen_tts.py", self.path, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["config"]["voice"], "zh-CN-XiaoyiNeural")
        self.spec["font"] = "missing.ttf"
        self.spec["scenes"] = [{"id": "s01", "image": "board.png", "regions": []}]
        self.save()
        result = self.cli("build_narration.py", self.path, "--preflight")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("font", result.stderr)

    def approve(self, mode="standard", through="G3"):
        note = self.root / "review.md"
        note.write_text("fixture reviewed", encoding="utf-8")
        gates = ("G0", "G1", "G2", "G3")
        for gate in gates[:gates.index(through) + 1]:
            artifact = self.path if gate == "G3" else note
            extra = ["--mode", mode] if gate == "G3" else []
            result = self.cli(
                "user_gates.py", "--root", self.root, "approve", gate,
                "--artifact", artifact, *extra,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result = self.cli("user_gates.py", "--root", self.root, "confirm", gate,
                              "--note", f"用户确认 {gate}")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_g3_records_the_effective_fast_configuration(self):
        self.spec.pop("rate")
        self.save()
        self.approve("fast")
        state = json.loads((self.root / ".user-gates.json").read_text(encoding="utf-8"))
        config = state["G3"]["narration"][str(self.path.resolve())]
        self.assertEqual(config["rate"], "+22%")
        self.assertTrue(config["trim"])
        result = self.cli("build_narration.py", self.path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("G3", result.stderr)
        self.assertFalse((self.root / "audio").exists())

    def run_narration(self, script="build_narration", *args):
        output = io.StringIO()
        with patch.object(sys, "argv", [script, str(self.path), *args]), contextlib.redirect_stdout(output):
            result = importlib.import_module(script).main()
        self.assertIn(result, (None, 0))
        return output.getvalue()

    fake_tts = staticmethod(testkit.fake_tts)

    def test_changed_spoken_text_regenerates_only_the_affected_audio(self):
        self.spec["scenes"][0]["regions"].append({
            "box": [0, 0, 1000, 1000], "annotation": "unchanged",
        })
        self.save()
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            self.run_narration()
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[0], ("a b", "zh-CN-XiaoyiNeural", "+15%"))
            self.spec["scenes"][0]["regions"][0]["spoken_text"] = "A B"
            self.save()
            self.approve()
            self.run_narration()
            self.assertEqual(len(requests), 3)
            self.assertEqual(requests[-1][0], "A B")
            self.run_narration()
            self.assertEqual(len(requests), 3)
        plan = json.loads((self.root / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["scenes"][0]["regions"][0]["annotation"], "a_b")

    def test_scene_cli_does_not_reuse_audio_after_voice_changes(self):
        self.spec["scenes"] = [{"id": "s01", "text": "a_b", "spoken_text": "A B"}]
        self.save()
        self.approve("scene")
        requests = []
        output = self.root / "scene-audio"
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            self.run_narration("gen_tts", "--out-dir", str(output))
            self.spec["voice"] = "zh-CN-YunxiNeural"
            self.save()
            self.approve("scene")
            self.run_narration("gen_tts", "--out-dir", str(output))
        self.assertEqual([r[1] for r in requests], ["zh-CN-XiaoyiNeural", "zh-CN-YunxiNeural"])

    def test_each_run_owns_audio_cues_and_reuse_facts(self):
        self.spec["scenes"][0]["regions"].append({
            "box": [0, 0, 1000, 1000], "annotation": "second",
        })
        self.save()
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            self.run_narration()
            first = json.loads((self.root / "plan.json").read_text())
            first_audio = self.root / first["scenes"][0]["audio"]
            original_bytes = first_audio.read_bytes()
            self.spec["gap"] = 0.8
            self.save()
            self.approve()
            self.run_narration()
        second = json.loads((self.root / "plan.json").read_text())
        report = json.loads((self.root / second["narration"]["manifest"]).read_text())
        self.assertEqual(len(requests), 2)
        self.assertNotEqual(first["scenes"][0]["audio"], second["scenes"][0]["audio"])
        self.assertEqual(first_audio.read_bytes(), original_bytes)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["tts"], {"generated": 0, "reused": 2})
        self.assertGreater(second["scenes"][0]["regions"][1]["start"],
                           first["scenes"][0]["regions"][1]["start"])
        result = self.cli("verify_media.py", "--manifest",
                          self.root / second["narration"]["manifest"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fast_processing_reuses_raw_audio_but_owns_processed_results(self):
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            self.run_narration()
            first = json.loads((self.root / "plan.json").read_text())
            self.approve("fast")
            self.run_narration("build_narration_fast")
        second = json.loads((self.root / "plan.json").read_text())
        self.assertEqual(len(requests), 1)
        self.assertNotEqual(first["narration"]["run_key"], second["narration"]["run_key"])
        report = json.loads((self.root / second["narration"]["manifest"]).read_text())
        self.assertTrue(report["inputs"]["config"]["trim"])
        self.assertEqual(report["tts"], {"generated": 0, "reused": 1})

    def test_legacy_audio_is_preserved_and_corrupt_cache_is_not_reused(self):
        legacy = self.root / "audio/narration/parts/s01_r00.mp3"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy")
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            self.run_narration()
            raw = next((self.root / ".narration-cache/raw").glob("*.mp3"))
            raw.write_bytes(b"corrupt")
            metadata_path = raw.with_suffix(".mp3.json")
            metadata = json.loads(metadata_path.read_text())
            metadata["sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
            metadata_path.write_text(json.dumps(metadata))
            self.run_narration()
        self.assertEqual(len(requests), 2)
        self.assertEqual(legacy.read_bytes(), b"legacy")

    def test_failed_synthesis_does_not_replace_previous_plan(self):
        self.approve()
        with patch("edge_tts.Communicate", side_effect=self.fake_tts([])):
            self.run_narration()
        original = (self.root / "plan.json").read_bytes()
        self.spec["scenes"][0]["regions"][0]["annotation"] = "new text"
        self.save()
        self.approve()

        class InvalidRequest:
            async def save(self, filename):
                Path(filename).write_bytes(b"not media" * 400)

        with patch("edge_tts.Communicate", return_value=InvalidRequest()):
            with self.assertRaises(ValueError):
                self.run_narration()
        self.assertEqual((self.root / "plan.json").read_bytes(), original)
        reports = [json.loads(p.read_text()) for p in
                   (self.root / "audio/narration/runs").rglob("manifest.json")]
        self.assertEqual(sorted(r["status"] for r in reports), ["FAIL", "PASS"])

    def test_invalid_input_after_approval_calls_no_tts(self):
        self.spec["scenes"][0]["regions"][0]["box"] = [0, 900, 1000, 100]
        self.save()
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            with self.assertRaises(ValueError):
                self.run_narration()
        self.assertEqual(requests, [])
        self.assertFalse((self.root / "audio").exists())

    def test_source_changed_during_synthesis_cannot_publish_a_successful_plan(self):
        self.approve()
        factory = self.fake_tts([])

        def changing(text, voice, rate):
            self.spec["rate"] = "+30%"
            self.save()
            return factory(text, voice, rate)

        with patch("edge_tts.Communicate", side_effect=changing):
            with self.assertRaises((ValueError, SystemExit)):
                self.run_narration()
        self.assertFalse((self.root / "plan.json").exists())

    def assert_preflight_source_change_is_blocked(self, script="build_narration",
                                                 mode="standard", preview=False):
        self.approve(mode)
        original_run = subprocess.run
        changed = []
        requests = []

        def edit_during_tool_probe(command, *args, **kwargs):
            result = original_run(command, *args, **kwargs)
            if "-encoders" in command and not changed:
                if mode == "scene":
                    self.spec["scenes"][0]["text"] = "a revised script"
                else:
                    self.spec["scenes"][0]["regions"][0]["annotation"] = "a revised script"
                self.save()
                changed.append(True)
            return result

        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)), \
                patch("subprocess.run", side_effect=edit_during_tool_probe):
            with self.assertRaises((ValueError, SystemExit)):
                args = ["--out-dir", str(self.root / "scene-output")] if mode == "scene" else []
                if preview:
                    args.append("--preview")
                self.run_narration(script, *args)
        self.assertEqual(changed, [True])
        self.assertEqual(requests, [])
        self.assertFalse((self.root / "plan.json").exists())
        self.assertEqual(list(self.root.rglob("manifest.json")), [])

    def test_source_changed_during_preflight_cannot_be_bound_as_the_synthesized_script(self):
        self.assert_preflight_source_change_is_blocked()
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            self.run_narration()
        self.assertEqual([r[0] for r in requests], ["a revised script"])
        plan = json.loads((self.root / "plan.json").read_text())
        report = json.loads((self.root / plan["narration"]["manifest"]).read_text())
        self.assertEqual(report["inputs"]["source_sha256"],
                         hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(report["schema"], 2)

    def test_fast_preflight_source_change_stops_before_synthesis(self):
        self.assert_preflight_source_change_is_blocked("build_narration_fast", "fast")

    def test_scene_preflight_source_change_stops_before_synthesis(self):
        self.spec["scenes"] = [{"id": "s01", "text": "original scene"}]
        self.save()
        self.assert_preflight_source_change_is_blocked("gen_tts", "scene")

    def test_preview_preflight_source_change_stops_before_synthesis(self):
        self.spec["scenes"] = [{"id": "s01", "text": "original scene"}]
        self.save()
        self.assert_preflight_source_change_is_blocked("gen_tts", "scene", preview=True)

    def test_legacy_pass_receipt_cannot_relabel_old_audio_as_a_new_script(self):
        self.approve()
        with patch("edge_tts.Communicate", side_effect=self.fake_tts([])):
            self.run_narration()
        plan = json.loads((self.root / "plan.json").read_text())
        manifest = self.root / plan["narration"]["manifest"]
        self.spec["scenes"][0]["regions"][0]["annotation"] = "newly approved script"
        self.save()
        self.approve()
        legacy = json.loads(manifest.read_text())
        legacy["schema"] = 1
        legacy["inputs"]["source_sha256"] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(legacy))
        result = self.cli("verify_media.py", "--manifest", manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported", result.stderr)

    def test_competing_producer_is_rejected_before_another_tts_request(self):
        self.approve()
        attempts = []
        factory = self.fake_tts([])

        def competing(text, voice, rate):
            attempts.append(self.cli("build_narration.py", self.path))
            return factory(text, voice, rate)

        with patch("edge_tts.Communicate", side_effect=competing):
            self.run_narration()
        self.assertEqual(len(attempts), 1)
        self.assertNotEqual(attempts[0].returncode, 0)
        self.assertIn("Another narration producer", attempts[0].stderr)

    def test_legacy_g3_requires_reconfirmation_before_production(self):
        self.approve()
        path = self.root / ".user-gates.json"
        state = json.loads(path.read_text())
        state["G3"].pop("narration")
        path.write_text(json.dumps(state))
        result = self.cli("build_narration.py", self.path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reapprove G3", result.stderr)
        self.assertFalse((self.root / "audio").exists())

    def test_ordinary_approval_accepts_json_array_material(self):
        material = self.root / "outline.json"
        material.write_text('["review item"]')
        result = self.cli(
            "user_gates.py", "--root", self.root, "approve", "G0",
            "--artifact", material, input_text="CONFIRM G0\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_documented_contract_covers_each_promise_in_behavior(self):
        narration = (SCRIPTS.parent / "references/narration-workflow.md").read_text(encoding="utf-8")
        gates = (SCRIPTS.parent / "references/user-gates.md").read_text(encoding="utf-8")

        # 1. 用户确认顺序：approve 冻结、confirm 记录；未暂存直接 confirm 被拒
        self.assertIn("approve", gates)
        self.assertIn("confirm", gates)
        result = self.cli("user_gates.py", "--root", self.root, "confirm", "G0",
                          "--note", "未先 review")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no staged review", result.stderr)

        # 5. 预览复用条件：preview 需要 G2，未授权被拒且不产生缓存
        self.assertIn("--preview", narration)
        scenes = self.spec["scenes"]
        self.spec["scenes"] = [{"id": "s01", "text": "preview text"}]
        self.save()
        result = self.cli("gen_tts.py", self.path, "--preview",
                          "--out-dir", str(self.root / "preview"))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "preview").exists())
        self.assertFalse((self.root / ".narration-cache").exists())
        self.spec["scenes"] = scenes
        self.save()

        # 2. 缓存失效维度：实际文本、音色、语速与契约版本参与缓存身份
        for term in ("实际文本", "音色", "语速", "契约版本"):
            self.assertIn(term, narration)
        self.assertIn("原始合成与裁静音/格式转换分开", narration)
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            self.run_narration()
            first = json.loads((self.root / "plan.json").read_text())
            self.spec["rate"] = "+16%"
            self.save()
            self.approve()
            self.run_narration()
            second = json.loads((self.root / "plan.json").read_text())
        self.assertNotEqual(first["scenes"][0]["audio"], second["scenes"][0]["audio"])

        # 3. 运行清单缺失处理：缺失清单不凭目录名或空文件复用
        self.assertIn("schema 2", narration)
        result = self.cli(
            "verify_media.py", "--manifest", str(self.root / "missing.json"))
        self.assertNotEqual(result.returncode, 0)

        # 4. 参数约束：rate 必须为带符号百分比
        self.assertIn("rate", narration)
        self.spec["rate"] = "fast"
        self.save()
        result = self.cli("build_narration.py", self.path, "--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rate", result.stderr)
        self.spec["rate"] = "+15%"
        self.save()

    def test_shared_batch_entry_points_require_approval_before_outputs(self):
        import narration_production
        from user_gates import GateError

        output = self.root / "scene-output"
        calls = [
            lambda: narration_production.produce_regions(self.path),
            lambda: narration_production.produce_regions(self.spec, self.root),
            lambda: narration_production.produce_scenes(self.path, output=output),
        ]
        with patch("edge_tts.Communicate", side_effect=AssertionError("unexpected synthesis")):
            for call in calls:
                with self.subTest(call=call), self.assertRaises(GateError):
                    asyncio.run(call())
        self.assertFalse((self.root / ".narration-cache").exists())
        self.assertFalse((self.root / "audio").exists())
        self.assertFalse(output.exists())

    def test_direct_build_keeps_dry_result_and_published_plan_shape(self):
        from build_narration import build

        with patch("edge_tts.Communicate", side_effect=AssertionError("unexpected synthesis")):
            result = asyncio.run(build(self.spec, self.root, dry=True))
        self.assertEqual(result["scenes"], self.spec["scenes"])
        self.assertEqual(result["config"]["rate"], "+15%")
        self.assertFalse((self.root / ".narration-cache").exists())
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)), \
                contextlib.redirect_stdout(io.StringIO()):
            result = asyncio.run(build(self.spec, self.root, dry=False))
        self.assertEqual(result, json.loads((self.root / "plan.json").read_text()))
        self.assertEqual(len(requests), 1)
        self.assertIn("narration", result)
        self.assertIn("start", result["scenes"][0]["regions"][0])

    def test_preview_without_g3_reuses_raw_audio_in_later_batch(self):
        self.spec["scenes"] = [{"id": "s01", "text": "preview text"}]
        self.save()
        self.approve("scene", through="G2")
        state = self.root / ".user-gates.json"
        approved = state.read_bytes()
        preview_output = self.root / "preview"
        batch_output = self.root / "batch"
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            text = self.run_narration("gen_tts", "--preview", "--out-dir", str(preview_output))
            preview = json.loads(text.splitlines()[-1])
            audited = json.loads(state.read_text())
            self.assertNotIn("G3", audited)
            self.assertNotIn("G3", json.loads(approved))
            self.assertIn("preview", audited)
            self.assertEqual(preview["generated"], 1)
            self.approve("scene")
            batch = json.loads(self.run_narration(
                "gen_tts", "--out-dir", str(batch_output)).splitlines()[-1])
        self.assertEqual(len(requests), 1)
        self.assertEqual(batch["generated"], 0)
        self.assertEqual(batch["reused"], 1)
        self.assertNotEqual(preview["manifest"], batch["manifest"])
        for output, summary in ((preview_output, preview), (batch_output, batch)):
            timeline = json.loads((output / "timeline.json").read_text())
            manifest = self.root / summary["manifest"]
            self.assertEqual(timeline[0]["manifest"], summary["manifest"])
            report = json.loads(manifest.read_text())
            self.assertEqual(report["status"], "PASS")
            self.assertEqual((manifest.parent / report["artifact"]).name, "timeline.json")
            self.assertTrue((self.root / timeline[0]["file"]).is_file())

    def test_shared_preview_rejects_missing_g2_and_long_text(self):
        from narration_production import preview_sentence
        from user_gates import GateError

        output = self.root / "preview"
        for case, through, text in (
            ("missing G2", "G1", "preview text"),
            ("too long", "G2", "x" * 101),
        ):
            with self.subTest(case=case):
                self.spec["scenes"] = [{"id": "s01", "text": text}]
                self.save()
                self.approve("scene", through=through)
                requests = []
                with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)), \
                        contextlib.redirect_stdout(io.StringIO()), self.assertRaises(GateError):
                    asyncio.run(preview_sentence(self.path, output=output))
                self.assertEqual(requests, [])
                self.assertFalse(output.exists())
                self.assertFalse((self.root / ".narration-cache").exists())

    def test_publish_failure_preserves_previous_output_and_records_failed_run(self):
        region_spec = copy.deepcopy(self.spec)
        for mode in ("standard", "fast", "scene", "preview"):
            with self.subTest(mode=mode):
                self.spec = copy.deepcopy(region_spec)
                is_scene = mode in ("scene", "preview")
                if is_scene:
                    self.spec["scenes"] = [{"id": "s01", "text": f"old {mode}"}]
                self.save()
                self.approve("scene" if is_scene else mode,
                             through="G2" if mode == "preview" else "G3")
                script = "gen_tts" if is_scene else "build_narration_fast" if mode == "fast" else "build_narration"
                output = self.root / mode
                args = ["--out-dir", str(output)] if is_scene else []
                if mode == "preview":
                    args.append("--preview")
                target = output / "timeline.json" if is_scene else self.root / "plan.json"
                with patch("edge_tts.Communicate", side_effect=self.fake_tts([])):
                    self.run_narration(script, *args)
                    original = target.read_bytes()
                    before = set(self.root.rglob("manifest.json"))
                    if is_scene:
                        self.spec["scenes"][0]["text"] = f"new {mode}"
                    else:
                        self.spec["scenes"][0]["regions"][0]["annotation"] = f"new {mode}"
                    self.save()
                    self.approve("scene" if is_scene else mode,
                                 through="G2" if mode == "preview" else "G3")
                    replace = os.replace

                    def refuse_publication(source, destination):
                        if Path(destination).resolve() == target.resolve():
                            raise PermissionError("publication denied")
                        return replace(source, destination)

                    with patch("artifacts.os.replace", side_effect=refuse_publication), \
                            self.assertRaisesRegex(PermissionError, "publication denied"):
                        self.run_narration(script, *args)
                self.assertEqual(target.read_bytes(), original)
                failed = set(self.root.rglob("manifest.json")) - before
                self.assertEqual(len(failed), 1)
                self.assertEqual(json.loads(failed.pop().read_text())["status"], "FAIL")
                self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_failed_failure_receipt_preserves_original_publication_error(self):
        self.approve()
        target = self.root / "plan.json"
        replace = os.replace

        def refuse_publication_and_failure_receipt(source, destination):
            destination = Path(destination)
            if destination.resolve() == target.resolve():
                raise PermissionError("publication denied")
            if destination.name == "manifest.json" and json.loads(Path(source).read_text())["status"] == "FAIL":
                raise OSError("failure receipt denied")
            return replace(source, destination)

        with patch("edge_tts.Communicate", side_effect=self.fake_tts([])), \
                patch("artifacts.os.replace", side_effect=refuse_publication_and_failure_receipt), \
                self.assertRaisesRegex(OSError, "failure receipt denied") as raised:
            self.run_narration()
        self.assertIsInstance(raised.exception.__context__, PermissionError)
        self.assertEqual(str(raised.exception.__context__), "publication denied")
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
