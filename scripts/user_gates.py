"""Persistent, version-bound production approvals. Not a security boundary.

Confirmation happens in the conversation: ``approve`` stages a review and prints it,
``confirm`` records it once the user has answered. No terminal prompt is used.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from artifacts import atomic_json, file_digest, file_lock, fingerprint
from production import (CAPABILITIES, capability_check, narration_config,
                        load_document, load_document_and_hash)
from render_contract import validate_evidence
from teaching import artifact_design, teaching_plan


STATE_FILE = ".user-gates.json"
PENDING_FILE = ".user-gates.pending.json"
GATES = tuple(f"G{i}" for i in range(6))
ACTIONS = {"boards": "G2", "tts": "G3", "sample": "G3",
           "render": "G4", "deliver": "G5"}


class GateError(SystemExit):
    pass


def load(root: Path) -> dict:
    path = root / STATE_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        return data
    except (ValueError, OSError) as exc:
        raise GateError(f"BLOCKED: invalid approval file: {path}: {exc}")


def require(root: Path, gate: str, artifact: Path | None = None) -> None:
    root = root.resolve()
    data = load(root)
    for name in GATES[:GATES.index(gate) + 1]:
        record = data.get(name)
        if not isinstance(record, dict) or not record.get("artifacts"):
            raise GateError(f"BLOCKED: {name} approval missing in {root / STATE_FILE}")
        if name in ("G4", "G5"):
            try:
                proof, _ = validate_evidence(Path(record["evidence"]),
                                             "sample" if name == "G4" else "render")
                require_narration(root, proof["context"])
                if proof["context"]["key"] != record["render_key"]:
                    raise ValueError(f"{name} render context differs")
                if name == "G5" and record["render_key"] != data["G4"]["render_key"]:
                    raise ValueError("G5 does not match the confirmed G4 sample")
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise GateError(f"BLOCKED: {name} evidence is missing, stale or invalid: {exc}")
        try:
            for filename, expected in record["artifacts"].items():
                if file_digest(Path(filename)) != expected:
                    raise GateError(f"BLOCKED: {name} artifact changed: {filename}")
        except (OSError, TypeError, AttributeError) as exc:
            raise GateError(f"BLOCKED: {name} approval cannot be verified: {exc}")
    if artifact is not None:
        filename = str(artifact.resolve())
        if filename not in data[gate]["artifacts"]:
            raise GateError(f"BLOCKED: {gate} does not approve this input: {filename}")


def stage_review(root: Path, gate: str, artifacts: list[Path],
                 mode: str = "standard", capabilities: list[str] | None = None) -> dict:
    """Freeze what the user must review. Writes nothing to the approval file."""
    root = root.resolve()
    # Single pending slot: refuse a competing producer instead of losing its review.
    with file_lock(root / ".user-gates.lock", "approval"):
        return _stage(root, gate, artifacts, mode, capabilities)


def _stage(root: Path, gate: str, artifacts: list[Path],
           mode: str = "standard", capabilities: list[str] | None = None) -> dict:
    index = GATES.index(gate)
    if index:
        require(root, GATES[index - 1])
    parent_version = fingerprint(load(root).get(GATES[index - 1])) if index else None
    if not artifacts:
        raise GateError("BLOCKED: at least one artifact is required")
    files = {p.resolve() for p in artifacts}
    evidence = None
    proof = None
    if gate in ("G4", "G5"):
        try:
            stage_name = "sample" if gate == "G4" else "render"
            candidates = [p for p in files if p.suffix.lower() == ".json"
                          and isinstance(load_document(p), dict)
                          and load_document(p).get("stage") == stage_name]
            if len(candidates) != 1:
                raise ValueError(f"{gate} requires exactly one {stage_name} receipt")
            evidence = candidates[0]
            proof, dependencies = validate_evidence(evidence, stage_name)
            require_narration(root, proof["context"])
            if gate == "G5" and proof["context"]["key"] != load(root)["G4"]["render_key"]:
                raise ValueError("G5 does not match the confirmed G4 sample")
            files.update(dependencies)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise GateError(f"BLOCKED: {gate} evidence: {exc}")
    narration = {}
    designs = []
    parsed_hashes: dict[str, str] = {}
    # Bind referenced boards/audio too, not just the JSON pointing at them.
    for path in list(files):
        if path.suffix.lower() in (".json", ".yaml", ".yml"):
            content, parsed_hashes[str(path)] = load_document_and_hash(path)
            if path == evidence and fingerprint(content) != fingerprint(proof):
                raise GateError("BLOCKED: render evidence changed while its snapshot was read")
            if isinstance(content, dict):
                if gate == "G2":
                    design = artifact_design(content)
                    if design is not None:
                        designs.append(design)
                if gate == "G3" and "scenes" in content:
                    narration[str(path)] = narration_config(content, mode)
                for scene in content.get("scenes", []):
                    if not isinstance(scene, dict):
                        continue
                    for key in ("image", "audio"):
                        if scene.get(key):
                            files.add((path.parent / scene[key]).resolve())
    hashes = {str(p): parsed_hashes[str(p)] if str(p) in parsed_hashes else file_digest(p)
              for p in sorted(files)}
    checks = {}
    for name in capabilities or []:
        if gate != "G0":
            raise GateError("BLOCKED: capability preflight belongs to G0")
        if name not in CAPABILITIES:
            raise GateError(f"BLOCKED: unknown capability {name}; choose from {CAPABILITIES}")
        try:
            checks[name] = capability_check(name)
        except ValueError as exc:
            raise GateError(f"BLOCKED: {name} local preflight failed: {exc}")
    review = {"gate": gate, "artifacts": hashes, "narration": narration,
              "teaching_plans": [fingerprint(design) for design in designs],
              "designs": designs,
              "evidence": str(evidence) if evidence else None,
              "render_key": proof["context"]["key"] if proof else None,
              "capabilities": checks,
              "parent_version": parent_version}
    atomic_json(root / PENDING_FILE, review)
    return review


def print_review(review: dict) -> None:
    """The whole review, so the conversation shows exactly what gets recorded."""
    gate = review["gate"]
    print(f"Review {gate} — show these to the user and ask for confirmation:")
    for filename in review["artifacts"]:
        print(f"  {filename}")
    if review["narration"]:
        print("Effective narration: "
              + json.dumps(review["narration"], ensure_ascii=True))
    if review["evidence"] is not None:
        print(f"Evidence receipt: {review['evidence']}")
    if review.get("capabilities"):
        print("Capability preflight: "
              + json.dumps(review["capabilities"], ensure_ascii=True))
    if review["designs"]:
        print("Teaching design: "
              + json.dumps(review["designs"], ensure_ascii=True))
    print(f"Then run: user_gates.py --root <集目录> confirm {gate} "
          f'--note "<用户的确认原话>"')


def commit_review(root: Path, gate: str, note: str) -> None:
    """Record the staged review. The user confirms in conversation, not in a terminal."""
    root = root.resolve()
    note = note.strip()
    if not note:
        raise GateError("BLOCKED: --note must quote what the user said")
    path = root / PENDING_FILE
    if not path.exists():
        raise GateError(f"BLOCKED: no staged review in {path}; run approve {gate} first")
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise GateError(f"BLOCKED: invalid staged review file: {path}: {exc}")
    if not isinstance(review, dict) or review.get("gate") != gate:
        raise GateError(f"BLOCKED: staged review is for "
                        f"{review.get('gate') if isinstance(review, dict) else '?'}, "
                        f"not {gate}")
    print_review(review)
    print(f"User said: {note}")
    _record(root, gate, review, note)
    path.unlink(missing_ok=True)
    print(f"Recorded {gate}; downstream approvals cleared.")


def exempt(root: Path, gate: str, artifacts: list[Path], scopes: list[str],
           note: str, mode: str = "standard") -> None:
    """Record a user-declared exemption. The gate binds artifacts and typed
    evidence exactly like a confirmation; only the waived scope is listed.
    Technical checks cannot be exempted."""
    root = root.resolve()
    scopes = [s.strip() for s in scopes]
    if not scopes or any(not s for s in scopes):
        raise GateError("BLOCKED: exempt requires --scope entries naming what is waived")
    review = stage_review(root, gate, artifacts, mode)
    _record(root, gate, review, note, exempted=scopes)
    (root / PENDING_FILE).unlink(missing_ok=True)
    print(f"Recorded {gate} exemption: {scopes}; downstream approvals cleared.")


def _record(root: Path, gate: str, review: dict, note: str,
            exempted: list[str] | None = None) -> None:
    note = note.strip()
    if not note:
        raise GateError("BLOCKED: --note must quote what the user said")
    index = GATES.index(gate)
    # The conversation carries the delay now; re-check everything it could have moved.
    with file_lock(root / ".user-gates.lock", "approval"):
        for filename, expected in review["artifacts"].items():
            if file_digest(Path(filename)) != expected:
                raise GateError(f"BLOCKED: artifact changed since review: {filename}")
        if index:
            require(root, GATES[index - 1])
        data = load(root)
        if index and fingerprint(data.get(GATES[index - 1])) != review["parent_version"]:
            raise GateError(f"BLOCKED: {GATES[index - 1]} changed since review; review again")
        if review["evidence"] is not None:
            stage_name = "sample" if gate == "G4" else "render"
            proof, _ = validate_evidence(Path(review["evidence"]), stage_name)
            require_narration(root, proof["context"])
            if proof["context"]["key"] != review["render_key"]:
                raise GateError(f"BLOCKED: {gate} render context differs from the review")
        for name in GATES[index:]:
            data.pop(name, None)
        data[gate] = {"artifacts": review["artifacts"],
                      "confirmed_at": datetime.now(timezone.utc).isoformat(),
                      "note": note}
        if exempted:
            data[gate]["exempted"] = exempted
        if gate == "G3":
            data[gate]["narration"] = review["narration"]
        if gate == "G2":
            data[gate]["teaching_plans"] = review["teaching_plans"]
        if gate == "G0" and review.get("capabilities"):
            data[gate]["capabilities"] = review["capabilities"]
        if review["evidence"] is not None:
            data[gate].update({"evidence": review["evidence"],
                               "render_key": review["render_key"]})
        atomic_json(root / STATE_FILE, data)


def discard(root: Path, gate: str) -> None:
    """Drop a staged review the user rejected."""
    path = (root / PENDING_FILE).resolve()
    if path.exists():
        try:
            review = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise GateError(f"BLOCKED: invalid staged review file: {path}: {exc}")
        if isinstance(review, dict) and review.get("gate") != gate:
            raise GateError(f"BLOCKED: staged review is for {review.get('gate')}, not {gate}")
        path.unlink()
        print(f"Discarded staged {gate}.")
    else:
        print(f"Nothing staged for {gate}.")


def authorize_preview(root: Path, texts: list[str]) -> None:
    """Record a one-line probe the user allowed in conversation. Not a gate."""
    root = root.resolve()
    require(root, "G2")
    if len(texts) != 1 or not texts[0].strip() or len(texts[0]) > 100:
        raise GateError("BLOCKED: preview requires one nonempty text, at most 100 characters")
    with file_lock(root / ".user-gates.lock", "preview"):
        data = load(root)
        data["preview"] = {"text_sha256": fingerprint(texts[0]),
                           "confirmed_at": datetime.now(timezone.utc).isoformat()}
        atomic_json(root / STATE_FILE, data)
    print("Preview authorized in conversation; G3 is still required before bulk narration.")



def require_spec(root: Path, spec: dict, mode: str = "standard",
                 rate: str | None = None) -> Path:
    return require_spec_snapshot(root, spec, mode, rate)[0]


def require_spec_snapshot(root: Path, spec: dict, mode: str = "standard",
                          rate: str | None = None) -> tuple[Path, str, dict]:
    """Pin the parsed approved document and its hash from one byte read."""
    require(root, "G3")
    require_teaching(root, spec)
    record = load(root.resolve())["G3"]
    for filename in record["artifacts"]:
        path = Path(filename)
        if path.suffix.lower() not in (".json", ".yaml", ".yml"):
            continue
        document, digest = load_document_and_hash(path)
        if document == spec:
            if digest != record["artifacts"][filename]:
                raise GateError("BLOCKED: G3 source changed while its snapshot was read")
            snapshot = record.get("narration")
            if (isinstance(snapshot, dict)
                    and snapshot.get(filename) == narration_config(spec, mode, rate)):
                return path, digest, document
            raise GateError("BLOCKED: G3 effective configuration differs or is missing; reapprove G3")
    raise GateError("BLOCKED: G3 does not approve this narration spec")


def require_teaching(root: Path, spec: dict) -> None:
    design = teaching_plan(spec)
    if design is None:
        return
    require(root, "G2")
    record = load(root)["G2"]
    if fingerprint(design) in record.get("teaching_plans", []):
        return
    raise GateError("BLOCKED: G2 must confirm this teaching design; "
                    "older records reapprove G2 under the current design identity")


def require_render(root: Path, key: str) -> None:
    require(root, "G4")
    if load(root)["G4"].get("render_key") != key:
        raise GateError("BLOCKED: G4 does not approve this render configuration; create a new sample")


def require_narration(root: Path, context: dict) -> None:
    narration = context.get("narration")
    if narration is not None:
        approved = load(root)["G3"].get("narration", {})
        if not isinstance(approved, dict) or approved.get(narration["source"]) != narration["config"]:
            raise GateError("BLOCKED: G3 narration configuration changed; regenerate narration")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True,
                        help="Directory holding this episode's inputs and approvals")
    sub = parser.add_subparsers(dest="operation", required=True)
    approval = sub.add_parser("approve", help="Stage a review for the user; records nothing")
    approval.add_argument("gate", choices=GATES)
    approval.add_argument("--artifact", type=Path, action="append", required=True)
    approval.add_argument("--mode", choices=["standard", "fast", "scene"], default="standard",
                          help="G3 使用的配音入口；会展示实际音色、语速及处理配置")
    approval.add_argument("--capability", action="append", choices=CAPABILITIES,
                          default=None, help="G0 声明选用能力并检查本地条件；可重复")
    confirm = sub.add_parser("confirm", help="Record the staged review after the user answered")
    confirm.add_argument("gate", choices=GATES)
    confirm.add_argument("--note", required=True,
                         help="用户的确认原话；写入审批记录供审计")
    waive = sub.add_parser("exempt", help="Record a user-declared exemption for this gate")
    waive.add_argument("gate", choices=GATES)
    waive.add_argument("--artifact", type=Path, action="append", required=True)
    waive.add_argument("--scope", action="append", required=True,
                       help="豁免范围，可重复；技术检查不能豁免")
    waive.add_argument("--note", required=True,
                       help="用户的豁免原话；写入审批记录供审计")
    waive.add_argument("--mode", choices=["standard", "fast", "scene"], default="standard")
    drop = sub.add_parser("discard", help="Drop a staged review the user rejected")
    drop.add_argument("gate", choices=GATES)
    check = sub.add_parser("check")
    check.add_argument("gate", choices=GATES)
    check.add_argument("--artifact", type=Path)
    run = sub.add_parser("run", help="Guard a custom production command")
    run.add_argument("action", choices=ACTIONS)
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.operation == "approve":
        print_review(stage_review(args.root, args.gate, args.artifact, args.mode,
                                  args.capability))
    elif args.operation == "confirm":
        commit_review(args.root, args.gate, args.note)
    elif args.operation == "exempt":
        exempt(args.root, args.gate, args.artifact, args.scope, args.note, args.mode)
    elif args.operation == "discard":
        discard(args.root, args.gate)
    elif args.operation == "check":
        require(args.root, args.gate, args.artifact)
        print(f"PASS: {args.gate}")
    else:
        require(args.root, ACTIONS[args.action])
        command = args.command
        if command[:1] == ["--"]:
            command = command[1:]
        if not command:
            parser.error("a command is required")
        return subprocess.run(command, cwd=args.root, check=False).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
