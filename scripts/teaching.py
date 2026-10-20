"""Optional teaching design; independent of theme and rendering backends."""
from __future__ import annotations

import math


ROLES = {"title", "rule", "example", "mistake", "practice", "answer", "summary"}
FORMS = {"text", "structure", "steps", "compare", "formula", "chart"}


def validate_design(rows: list) -> list:
    if not rows:
        raise ValueError("Teaching design must contain scenes")
    ids = set()
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or not isinstance(row.get("role"), str)
                or row["role"] not in ROLES):
            raise ValueError("Every teaching scene requires a known role")
        sid = row.get("id")
        if not isinstance(sid, str) or not sid or sid in ids:
            raise ValueError("Teaching scene ids must be unique")
        ids.add(sid)
        visual = row.get("visual")
        if (not isinstance(visual, dict)
                or set(visual) != {"form", "objects", "change", "outcome", "order"}):
            raise ValueError(f"{sid}: visual requires form, objects, change, outcome and order")
        if not isinstance(visual["form"], str) or visual["form"] not in FORMS:
            raise ValueError(f"{sid}: unknown visual form")
        objects, order = visual["objects"], visual["order"]
        if (not isinstance(objects, list) or not 1 <= len(objects) <= 6
                or any(not isinstance(v, str) or not v.strip() for v in objects)
                or len(set(objects)) != len(objects)):
            raise ValueError(f"{sid}: visual.objects must name 1..6 distinct objects")
        if (not isinstance(order, list) or any(not isinstance(v, str) for v in order)
                or sorted(order) != sorted(objects)):
            raise ValueError(f"{sid}: visual.order must order every object exactly once")
        if not isinstance(visual["change"], str) or not visual["change"].strip():
            raise ValueError(f"{sid}: describe the visual change or static relationship")
        if not isinstance(visual["outcome"], str) or not visual["outcome"].strip():
            raise ValueError(f"{sid}: state the outcome the visual produces")
        if not isinstance(row.get("narration"), list) or any(
                not isinstance(text, str) for text in row["narration"]):
            raise ValueError(f"{sid}: teaching narration must be text")
        hold = row.get("hold", 0)
        if (isinstance(hold, bool) or not isinstance(hold, (int, float))
                or not math.isfinite(hold) or not 0 <= hold <= 120):
            raise ValueError(f"{sid}: hold must be within 0..120 seconds")
        if hold and row["role"] != "practice":
            raise ValueError(f"{sid}: only practice scenes have a thinking hold")
        if row["role"] == "practice" and (index + 1 == len(rows)
                                          or not isinstance(rows[index + 1], dict)
                                          or rows[index + 1].get("role") != "answer"):
            raise ValueError(f"{sid}: practice must be followed by an answer scene")
        if row["role"] == "answer" and (index == 0 or rows[index - 1]["role"] != "practice"):
            raise ValueError(f"{sid}: answer must follow its practice scene")
    # Approval identity follows the design, not JSON numeric or empty-slot spelling.
    return [{**row, "hold": float(row.get("hold", 0)),
             "narration": [text for text in row["narration"] if text.strip()]}
            for row in rows]


def teaching_plan(spec: dict) -> list | None:
    enabled = spec.get("teaching", False)
    if not isinstance(enabled, bool):
        raise ValueError("teaching must be true or false")
    if not enabled:
        if any(scene.get("hold", 0) for scene in spec.get("scenes", [])):
            raise ValueError("Thinking hold requires explicit teaching mode")
        return None
    rows = []
    for scene in spec.get("scenes", []):
        rows.append({
            "id": scene.get("id"), "role": scene.get("role"),
            "visual": scene.get("visual"), "hold": scene.get("hold", 0),
            "narration": [r.get("annotation", "") for r in scene.get("regions", [])]
                         if "regions" in scene else [scene.get("text", "")],
        })
    return validate_design(rows)


def artifact_design(document: dict) -> list | None:
    if document.get("teaching"):
        return teaching_plan(document)
    rows = document.get("teaching_plan")
    if rows is None:
        return None
    if not isinstance(rows, list):
        raise ValueError("Teaching design report must contain a scene array")
    return validate_design(rows)
