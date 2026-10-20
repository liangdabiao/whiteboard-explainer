# edge-tts 被封时的替代方案：apiz

> 面向用户与 AI agent。当 `edge-tts` 报`WSServerHandshakeError 403` 时走这一条。
> 实测环境：Windows，本机 edge-tts 已被微软全域封锁，apiz 方案 35 片旁白 0 失败。

---

## 0. 先确认 edge-tts 真的不能用

403 是**长期按 IP/地区封锁**，不是偶发抖动，重试没有意义：

G2 后准备单句 `preview.json`，按 G3 单独获准再试听：

```bash
python scripts/gen_tts.py preview.json --preview --out-dir preview_audio
```

若改用付费 apiz，先说明费用并重新确认后端与音色，不自动切换或产生调用。

报错长这样：

```
WSServerHandshakeError 403, message='Invalid response status',
url='wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?...'
```

看到就换 apiz。

---

## 1. apiz 是什么

**[NEX AI](https://apiz.ai/)** —— 面向 AI agent 的模型网关。图像 / 视频 / 语音都有，
提供 CLI、Python SDK、TypeScript/Go SDK、MCP server，可直接接进 Codex / Claude Code / Cursor。

本skill 只用到它的 **语音合成（TTS）** 与 **强制对齐（align）** 两项。

- 官网：https://apiz.ai/
- 仓库：https://github.com/xuliang2024/apiz-sdk（Apache-2.0）
- key 申请：https://apiz.ai/#/api-keys
- 计费：1 积分 = 0.01 元，按量计费

与 edge-tts 的差别：

| | edge-tts | apiz speak |
|---|---|---|
| 成本 | 免费 | 按量（turbo 档很便宜） |
| 限流 | 无 | 无 |
| 音色 | 少量 | 300+ 公共音色，中文几十种 |
| 稳定性 | **经常被 403** | 正常 |

---

## 2. 安装与登录

```bash
# 一键安装（自动识别系统/架构，文件托管在 Cloudflare R2）
curl -fsSL https://apiz.ai/cli | sh        # macOS / Linux
# Windows PowerShell
scoop install apiz
# 或
brew install apiz-ai/tap/apiz

# 登录
apiz auth login --api-key sk-xxxxxxxx

# 查余额（重要：余额不足时所有模型一起挂）
apiz account balance
```

配置优先级：`--api-key` 参数 > `APIZ_API_KEY` 环境变量 > `~/.config/apiz/config.toml` profile。

> ⚠️ **余额闸门**：余额 < 10 元时，**所有**模型都返回 `HTTP 429 余额不足`（不只 TTS）。
> 充值后立即恢复。排查时先跑 `apiz account balance`。

---

## 3. 语音合成

```bash
# 看全部音色
apiz voices list --json
# → {"user_voices": [], "public_voices": [{"voice_id","voice_name","tags","audio_url"}, ...]}

# 合成
apiz speak "要合成的文本" \
  --model speech-2.6-turbo \
  --voice "Chinese (Mandarin)_Warm_Bestie" \
  --speed 1.22 \
  --output-file out/tts.mp3
```

| 参数 | 说明 |
|---|---|
| `--model` | 四档：`speech-2.8-hd` / `speech-2.8-turbo` / `speech-2.6-hd` / `speech-2.6-turbo`。**默认 2.8-hd，最省用 2.6-turbo** |
| `--voice` | 省略则自动挑第一个公共音色 |
| `--speed` | 0.5–2.0，**替代 edge-tts 的 `rate="+22%"`**（1.22 ≈ +22%） |
| `--output-file` | 存成 mp3 |

中文讲解音色（`tags` 含「中文」）：

- `Chinese (Mandarin)_Warm_Bestie` —— 温暖闺蜜声，长篇讲解不累
- `Chinese (Mandarin)_Gentleman` —— 温润男声，适合历史/科普

### ⚠️ 两个必须知道的坑

**1. 用 `apiz speak`，不要用 `apiz generate --model minimax/t2a`**

后者走异步任务模型：只返回 `task_id` / `status` / `price`，**不返回音频**，而且没有 `--out` 参数 → 拿不到声音。

**2. `--json` 是非 TTY 环境的默认值**

脚本里调用时若想拿结构化输出，显式加 `--json`；人类终端里它会打印表格，加 `--table` 更友好。

---

## 4. 强制对齐（顺带能力）

本skill 靠「每个 region 子句单独合成」拿精确 cue。如果你手上**已有一整段音频**，
只想知道每句话的时间点，用 `apiz align`：

```bash
apiz align "对应的文字内容" --audio https://example.com/talk.mp3
# → 逐字毫秒时间戳，直接写进 plan.json 的 region.start / region.end
```

约束：音频需是 URL（mp3/wav/m4a），≤120 分钟。

---

## 5. 完整脚本：`build_voice.py`

这是实测跑通的版本：逐 region 合成 → 把**真实时长**写回 `plan.json` 作为精确 cue →
用 gap 静音拼成每拍音轨。

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_voice.py — 用 apiz speak 生成旁白并回填精确 cue

用法：
    python build_voice.py                      # 读同目录 plan.build.json，写 plan.json
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent
PLAN = PROJ / "plan.build.json"
OUT_DIR = PROJ / "audio" / "narration"

VOICE = "Chinese (Mandarin)_Warm_Bestie"
MODEL = "speech-2.6-turbo"      # 最低档
SPEED = "1.22"                 # ≈ edge-tts rate +22%
GAP = 0.2                      # 句间停顿（秒）


def probe_duration(p: Path) -> float:
    """读音频时长。用 ffmpeg 解析，因为本机可能没有 ffprobe。"""
    import theme as TH          # skill 自带 ffmpeg 定位
    ff = TH.ffmpeg_path()
    r = subprocess.run([ff, "-i", str(p)], capture_output=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr)
    if not m:
        raise RuntimeError(f"读时长失败: {p}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def main() -> int:
    spec = json.loads(PLAN.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    parts = OUT_DIR / "parts"
    parts.mkdir(exist_ok=True)

    for scene in spec["scenes"]:
        sid = scene["id"]
        clips = []
        for i, r in enumerate(scene["regions"]):
            ann = r.get("annotation")
            if not ann:
                continue                      # 无旁白 = 纯图形
            dst = parts / f"{sid}_{i:02d}.mp3"
            # skip 已存在，避免重复付费
            if not dst.exists() or dst.stat().st_size < 2048:
                r0 = subprocess.run(
                    ["apiz", "speak", ann, "--model", MODEL,
                     "--voice", VOICE, "--speed", SPEED,
                     "--output-file", str(dst)],
                    capture_output=True, encoding="utf-8", errors="replace")
                if r0.returncode != 0 or not dst.exists() or dst.stat().st_size < 2048:
                    print(f"  [{sid}] 第{i}片失败: {(r0.stderr or r0.stdout)[:160]}")
                    return 1
            clips.append(dst)

        if not clips:
            continue

        # ① 按各片真实时长累加 → region.start / end（这就是精确 cue）
        t, ci = 0.0, 0
        for reg in scene["regions"]:
            if not reg.get("annotation"):
                continue
            dur = probe_duration(clips[ci])
            reg["start"] = round(t, 3)
            reg["end"] = round(t + dur, 3)
            t += dur + GAP
            ci += 1

        # ② concat：分片之间插 gap 静音
        import theme as TH
        ff = TH.ffmpeg_path()
        silent = parts / f"{sid}_gap.mp3"
        subprocess.run([ff, "-y", "-f", "lavfi", "-i",
                        "anullsrc=r=44100:cl=mono", "-t", str(GAP),
                        "-q:a", "9", str(silent)], capture_output=True)

        seq = []
        for i, c in enumerate(clips):
            seq.append(str(c))
            if i < len(clips) - 1:
                seq.append(str(silent))
        listf = parts / f"{sid}_list.txt"
        listf.write_text("\n".join(f"file '{Path(x).resolve().as_posix()}'"
                                   for x in seq), encoding="utf-8")

        out = OUT_DIR / f"{sid}.mp3"
        r1 = subprocess.run([ff, "-y", "-f", "concat", "-safe", "0",
                             "-i", str(listf), "-c:a", "libmp3lame",
                             "-q:a", "2", str(out)], capture_output=True)
        if r1.returncode != 0 or not out.exists():
            print(f"  [{sid}] concat 失败: {r1.stderr.decode('utf-8','replace')[-200:]}")
            return 1

        real = probe_duration(out)
        scene["audio"] = f"audio/narration/{sid}.mp3"
        scene["duration"] = round(real, 3)
        # 末段end 对齐真实总长
        for reg in reversed(scene["regions"]):
            if reg.get("end"):
                reg["end"] = round(real, 3)
                break
        print(f"  [{sid}] {real:.2f}s  {out.stat().st_size//1024}KB")

    (PROJ / "plan.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成 → {PROJ / 'plan.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 接回主流程

```bash
python build_voice.py                     # 生成旁白 + plan.json
python scripts/check_assignment.py plan.json   # 质检：必须 TOTAL unassigned: 0
python scripts/render_explainer.py plan.json --out out/x.mp4
```

> ⚠️ 改了 `make_boards.py` 的 region box 后**必须重跑 `build_voice.py`**——
> `check_assignment.py` 读的是 `plan.json`，不是 `plan.build.json`。

---

## 6. 排错速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `WSServerHandshakeError 403` | edge-tts 被封 | 换 apiz（本文档） |
| 所有模型都 `HTTP 429 余额不足` | 余额 < 10 元触发全局闸门 | `apiz account balance` →充值 |
| `apiz generate` 建了任务但没音频 | 用错子命令 | 必须 `apiz speak --output-file` |
| 拿到的 mp3 是 0 字节 | 合成失败但文件已创建 | 脚本里已加`size < 2048` 判空重试 |
| `command not found: apiz` | 未装或不在 PATH | 见第 2 节；Windows 用 scoop |
| 音色名写错 | voice_id 拼写不对 | `apiz voices list --json` 查准确 id |