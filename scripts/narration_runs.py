"""A narration run owns its processed audio, cue plan and evidence."""
from __future__ import annotations

import uuid
import json
from pathlib import Path

from artifacts import SHARED_IMPLEMENTATION, atomic_json, file_digest, fingerprint, relative
from media import verify


VERSION = 2


def read_run(path: Path) -> tuple[dict, set[Path]]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(report, dict) or report.get("schema") != VERSION
                or report.get("stage") != "narration" or report.get("status") != "PASS"):
            raise ValueError("incomplete or unsupported run")
        artifact = (path.parent / report["artifact"]).resolve()
        if file_digest(artifact) != report["artifact_sha256"]:
            raise ValueError("plan fingerprint changed")
        files = {path.resolve(), artifact}
        if "source" not in report["inputs"]:
            raise ValueError("legacy narration run needs regeneration to record its source")
        source = Path(report["inputs"]["source"])
        if file_digest(source) != report["inputs"]["source_sha256"]:
            raise ValueError("narration source changed; regenerate the narration run")
        files.add(source.resolve())
        for item in report["media"]:
            audio = (path.parent / item["path"]).resolve()
            if item["kind"] != "audio" or file_digest(audio) != item["sha256"]:
                raise ValueError("audio fingerprint changed")
            files.add(audio)
        return report, files
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Narration run is missing, stale or invalid: {exc}") from exc


class NarrationRun:
    def __init__(self, root: Path, spec: dict, config: dict,
                 source: Path, output: Path | None = None, *, source_sha256: str):
        if file_digest(source) != source_sha256:
            raise ValueError("Narration source changed during preflight; reload and confirm the input")
        self.root = root.resolve()
        self.source = source
        self.images = {s["id"]: root / s["image"] for s in spec["scenes"] if s.get("image")}
        implementation = {
            name: file_digest(Path(__file__).with_name(name))
            for name in (*SHARED_IMPLEMENTATION, "narration_cache.py", "narration_runs.py",
                         "narration_production.py", "build_narration.py",
                         "build_narration_fast.py", "gen_tts.py")
        }
        inputs = {
            "source": str(source.resolve()), "source_sha256": source_sha256, "config": config,
            "images": {s["id"]: file_digest(root / s["image"])
                       for s in spec["scenes"] if s.get("image")},
            "implementation": implementation,
        }
        self.key = fingerprint({"version": VERSION, **inputs})
        self.id = uuid.uuid4().hex
        base = output if output is not None else root / spec.get("audio_dir", "audio/narration")
        self.directory = base / "runs" / self.key / self.id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.manifest = self.directory / "manifest.json"
        self.report: dict = {
            "schema": VERSION, "stage": "narration", "status": "RUNNING",
            "run_key": self.key, "run_id": self.id, "inputs": inputs,
            "tts": {"generated": 0, "reused": 0}, "media": [], "scenes": [],
        }
        atomic_json(self.manifest, self.report)

    def record(self, sid: str, path: Path | None, regions: list, facts: list[dict],
               timing: dict | None = None) -> None:
        for entry in facts:
            for field in ("generated", "reused"):
                self.report["tts"][field] += entry[field]
        scene: dict = {"id": sid, "regions": regions, "sources": facts}
        scene.update(timing or {})
        if path is not None:
            result = verify(path, kind="audio")
            item = {
                "path": relative(path, self.directory), "expect": result["duration"],
                "sha256": file_digest(path), "kind": "audio",
            }
            self.report["media"].append(item)
            scene.update({"audio": item["path"], "duration": result["duration"],
                          "checks": result})
        else:
            scene["checks"] = {"audio": "SKIP", "reason": "silent scene"}
        self.report["scenes"].append(scene)

    def complete(self, payload: object, name: str = "plan.json") -> dict:
        if file_digest(self.source) != self.report["inputs"]["source_sha256"]:
            raise ValueError("Narration input changed during synthesis; approve the new input")
        if any(file_digest(path) != self.report["inputs"]["images"][sid]
               for sid, path in self.images.items()):
            raise ValueError("A board changed during synthesis; approve the new input")
        atomic_json(self.directory / name, payload)
        self.report.update({
            "status": "PASS", "artifact": name,
            "artifact_sha256": file_digest(self.directory / name),
        })
        atomic_json(self.manifest, self.report)
        return {"run_key": self.key, "run_id": self.id,
                "manifest": relative(self.manifest, self.root),
                **self.report["tts"]}

    def fail(self) -> None:
        self.report["status"] = "FAIL"
        atomic_json(self.manifest, self.report)
