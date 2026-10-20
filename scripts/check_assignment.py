#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_assignment.py — 渲染前质检:plan.json 中每个连通组件必须能归属到某个 region。

原理:用引擎同款流程(_enforce_white_bg + _downscale + _find_components)找出底图上的
全部墨迹组件,按 plan 的 region box 检查"中心包含 或 覆盖率>=25%"。未归属的组件会被
引擎兜底安排到不可控的绘制窗口,造成"讲到 A 时 B 提前画出来"。

用法:
  python check_assignment.py plan.json
退出码:0 = 全部归属;1 = 存在未归属组件(逐条列明细)。
"""
import json
import sys
from pathlib import Path

import numpy as np
from whiteboard_animator import WhiteboardAnimator
from boards import board_image


def region_boxes(region, sw, sh):
    raw = region.get("box", region.get("box_2d"))
    items = raw if isinstance(raw, list) and raw and isinstance(raw[0], (dict, list, tuple)) else [raw]
    out = []
    for b in items:
        if isinstance(b, dict):
            b = [b["ymin"], b["xmin"], b["ymax"], b["xmax"]]
        ymin, xmin, ymax, xmax = [int(v) for v in b]
        out.append((region.get("label", "?"),
                    xmin / 1000 * sw, ymin / 1000 * sh,
                    xmax / 1000 * sw, ymax / 1000 * sh))
    return out


def audit(plan: dict, root: Path, canvas: list[int] | None = None) -> dict:
    an = WhiteboardAnimator(fade_duration=0.06)
    failures = []
    checked = False
    for scene in plan["scenes"]:
        if not scene.get("regions"):
            continue
        checked = True
        img = np.array(board_image(root / scene["image"], canvas))
        small = an._enforce_white_bg(an._downscale(img))
        comps = an._find_components(small)
        sw, sh = small.shape[1], small.shape[0]
        boxes = []
        for r in scene.get("regions", []):
            boxes.extend(region_boxes(r, sw, sh))
        for i, c in enumerate(comps):
            x0, y0, x1, y1 = c["left"], c["top"], c["right"], c["bottom"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            area = max((x1 - x0) * (y1 - y0), 1)
            owned = False
            for _, bx0, by0, bx1, by1 in boxes:
                if bx0 <= cx <= bx1 and by0 <= cy <= by1:
                    owned = True
                    break
                inter = (max(0, min(x1, bx1) - max(x0, bx0))
                         * max(0, min(y1, by1) - max(y0, by0)))
                if inter / area >= 0.25:
                    owned = True
                    break
            if not owned:
                failures.append({"scene": scene["id"], "component": i,
                                 "box": [int(x0), int(y0), int(x1), int(y1)]})
    return {"state": "FAIL" if failures else ("PASS" if checked else "SKIP"),
            "unassigned": failures}


def main() -> int:
    plan_path = Path(sys.argv[1] if len(sys.argv) > 1 else "plan.json").resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    result = audit(plan, plan_path.parent, plan.get("canvas"))
    for failure in result["unassigned"]:
        print(f"{failure['scene']} UNASSIGNED comp{failure['component']} bbox={failure['box']}")
    print(f"ASSIGNMENT {result['state']}")
    print(f"TOTAL unassigned: {len(result['unassigned'])}")
    return 1 if result["state"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
