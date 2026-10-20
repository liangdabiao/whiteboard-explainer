---
name: whiteboard-explainer
version: 1.1.0
display_name: 白板讲解动画
display_name_en: Whiteboard Explainer
description_zh: 白板讲解动画 skill：把知识讲解/科普/推导内容变成「真手绘过程」视频——白板图上的图形被一笔笔描出来、文字逐笔写出、讲到哪画到哪（帧级音画对齐）。基于 whiteboard-animator 引擎（本地 CPU 渲染、零 API 成本、确定性可重渲）。当用户要做知识讲解视频、概念科普、数学/流程推导、数据图表讲解，或要求"手绘白板动画"、"讲解画面逐笔绘制"、"讲到哪画到哪"时使用。文章/教程/文档转讲解视频时，优先走「教学讲稿流程」(references/teaching-script.md)：先写讲稿自检，再制作。**硬性用户确认闸门**见 references/user-gates.md（讲稿风格、讲稿内容、TTS 音色未确认不得绘图/配音/渲染）。触发词：白板动画、白板讲解、手绘讲解、explainer、知识科普视频、讲到哪画到哪、逐笔绘制、whiteboard、文章转视频、教程讲解。
description_en: 'Whiteboard explainer skill that turns knowledge explainers into true hand-drawn process videos with frame-level A/V sync. Hard user confirmation gates (script style, script content, TTS voice) are required before boards/TTS/render — see references/user-gates.md. Use for educational explainer videos, concept explainers, math/process derivations, or whiteboard animation requests.'
description: 白板讲解动画 skill：把知识讲解/科普/推导内容变成「真手绘过程」视频——图形一笔笔描出、文字逐笔写出、讲到哪画到哪。**文章/教程优先走 teaching-script.md。硬性：未过 user-gates.md 的 G1 风格 / G2 讲稿 / G3 音色确认，不得绘图、配音、全量渲染；禁止一路干到底。** 书籍章节系列另见 references/book-chapter-video.md。触发词：白板动画、白板讲解、手绘讲解、explainer、知识科普视频、讲到哪画到哪、逐笔绘制、whiteboard、文章转视频、教程讲解。
---

# Whiteboard Explainer（白板讲解动画）

把讲解稿变成白板手绘动画：每拍一张白板图，图形按笔画绘出、文字逐笔写出，**元素级精确对齐旁白（讲到哪画到哪）**。

## ★ 用户确认闸门（硬性，优先于一切制作步骤）

**禁止**在未获用户明确同意时连续完成「写稿→画板→配音→渲染」。  
完整协议、选项表、确认话术模板见 **`references/user-gates.md`**。开做前必须读。
脚本审批入口：`scripts/user_gates.py`。每集独立保存 `.user-gates.json`；确认在对话中完成（`approve` 打印待确认内容，用户回答后 `confirm --note "<用户原话>"`），文件变更使确认失效。自定义绘图/TTS 命令必须用其 `run` 子命令包裹，详见上述协议。
内置配音的本地预检、G3 与配音清单见 **`references/narration-workflow.md`**。视频缓存、类型化 G4/G5 回执、可选教学设计与停顿见 **`references/render-workflow.md`**。

| 闸 | 确认什么 | 未通过时禁止 |
|---|---|---|
| G1 | **讲稿风格**（推荐一问一答；另有独白 / 苏格拉底追问） | 写完整 `讲稿.md`（可先列覆盖度清单） |
| G2 | **讲稿内容**（`讲稿.md` + 自检 + 覆盖度；重要篇章附分章摘要） | `make_boards` / 出图 |
| G3 | **TTS 语音**（单独获准后探测或试听；用户选定音色与语速再批量配音） | 未获准的 TTS / 批量 `build_narration*` |
| G4 | **冒烟一拍**抽帧 | 全量 `render_explainer` |
| G5 | **最终成片**（完整视频 + 技术质检结果 + 已知问题） | 标记整个制作任务交付完成 |

用户说「全部按推荐、不要再问」时，才可跳过对应闸，并在回复写明跳过了哪几闸。  
一问一答的写法（角色列、`问：`/`答：`、分 region）见 `user-gates.md` 与 `teaching-script.md`。

**和另外两个手绘 skill 的区别**：`story-handdrawn-remotion` 是静帧擦除（假手绘）；`story-handdrawn-video` 是 Agnes 文生视频（真动但不可控）；本 skill 是**像素级笔画绘制**——帧帧确定、本地零成本、可秒级重渲，且支持"一图逐元素生长"的单画布模式（前两者做不到）。

**工具链**：whiteboard-animator 引擎（官方 PyPI 包 `==0.1.1`，首次 setup 自动安装，自带 CRAFT 文字检测模型 craft.onnx 约 83MB）+ Agnes Image 2.1（白板风生图，免费）+ PIL（确定性中文文字层）+ **旁白 TTS（edge-tts 被 403 封锁时改用 [apiz](https://apiz.ai/) CLI）** + ffmpeg。

> ⚠️ **edge-tts 很可能不可用**：它按 IP/地区被微软封锁，报
> `WSServerHandshakeError 403` 时重试无意义，**必须换 apiz**。
> 第一集讲稿确认后，按 G3 准备单句 `preview.yaml`，再交互授权探测：`python scripts/gen_tts.py preview.yaml --preview --out-dir preview_audio`。
> 403 → 走 `references/apiz-tts-fallback.md`（含安装、登录、可用音色、完整 `build_voice.py`）。

**安装（下载后只要 1 步）**：

| 平台 | 命令 |
|---|---|
| macOS / Linux / Git Bash | `bash scripts/setup.sh` |
| Windows PowerShell | `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1` |

脚本会建 venv、装依赖（`whiteboard-animator==0.1.1` 引擎，约 83MB 的 CRAFT 模型随 pip 从 PyPI 下载，onnxruntime / edge-tts / Pillow / numpy 等传递依赖自动装上）、检查 ffmpeg 路径（缺失会报错并提示安装）。装完用 `source .venv/bin/activate`（或 `.venv\Scripts\Activate.ps1`），所有 `scripts/*.py` 都在 venv 里直接 `python scripts/xxx.py` 即可。

**质量原则（画面 70% 即交付）**：仅作用于**已过用户确认闸之后**的画面微调——单拍构图对、元素对就过，不逐拍修图。渲染本地零成本，重渲比修图便宜；遵守"skip 已存在"纪律。**不得**用本原则跳过 G1–G5。

## ★ 概念短视频系列（一篇文章一集，已验证量产管线）

做商业/心理/经济**概念科普系列短视频**（如《5分钟商学院》一文章一集）时，走
**`references/concept-short-video.md`**，并**叠加** `user-gates.md`（每集 G2→G5；系列开头确认 G0/G1/G3）。
工程管线：`make_boards.py` → `build_narration_fast.py` → check_assignment → 冒烟 → 全量 → verify_media → G5 成片确认。
竖屏 720×1280。系列任务先读 concept 文档与 user-gates。

## ★ 深度内容科普系列（经典书+最新深调研，硬性标准流程）

做"经典书/学科框架 + 最新动态深调研"的深度科普系列时，
**必须**走 **`references/deep-fact-series.md`**，并**叠加** `user-gates.md`。
每集制作前 2–6 次真实搜索；`lib/audit_boards.py` 防重叠；
交付定义 = 用户闸通过（含当前版本 G5 确认或明确豁免）+ 审计全绿 + 双轮归属 0 + verify PASS + 抽帧目检通过。

## ★ 文章/教程 → 讲解视频:教学讲稿流程(此类任务优先走这条)

输入是文章/教程/文档时,**先确认后制作**。完整方法见 **`references/teaching-script.md`** + **`references/user-gates.md`**。要点:

1. **G1 风格**：推荐一问一答；用户选定后再写稿。禁止默认独白一路写完。
2. **G2 讲稿**：`讲稿.md` 自检通过后停，用户确认才画板。重要篇章附分章摘要。
3. **问题驱动 + 覆盖度**：开场/概念前有问；原文知识点与图片不漏；例子用真材料；≥1 启发点。
4. **G3 音色**：探测 TTS 后端后贴选项；用户选定 voice/rate 再配音。单拍旁白 ≤50 字。
5. **G4 + 质检**：`check_assignment` 清零 → 冒烟抽帧经用户同意 → 全量渲染。
6. **G5 成片确认**：技术质检后提交完整视频，按 `user-gates.md` 等待当前版本确认，才标记交付完成。

## 成片模式（两种）

| 模式 | 适用 | 做法 |
|---|---|---|
| **slide 序列**（默认） | 逐句讲解、步骤演示 | 一拍一图，每拍独立渲染后 concat |
| **单画布生长** | 数学推导、流程图、知识图谱 | 一张大图 + 多 region + 逐句 cue，画面持续累积 |

## 原声直用工作流（中文播客/讲解 → 白板视频，无 lrc 时）

已有成片原声（mp3）+ 文字脚本（md/txt）、不想重新配音时，**不要**用 build_narration（那是 TTS 路线），
改用 `scripts/transcribe_align.py`（借鉴 story-handdrawn-remotion 的时间轴思路 + faster-whisper）：

```bash
python scripts/transcribe_align.py 原声.mp3 脚本.md 项目目录
# 产出 项目目录/transcript.json、sentences.txt、timeline.json（每场 sentences=一句一拍文案）
```

- 长音频自动分块转写（避免内存峰值）；模型下载走 HF_ENDPOINT=https://hf-mirror.com + HF_HUB_DISABLE_XET=1
- 对齐：句子按字数比例估计时间 → 吸附最近转写分段起点（±8s）→ 单调钳制
- 然后：按 timeline.json 的每场 sentences 排版画面文案 → 渲染时用原声 mp3 按场切片

姊妹 skill 参考（工程方法同源，值得对照）：story-handdrawn-remotion（Remotion 渲染/资产 hash 纪律/
preview 即成物）、story-handdrawn-video。

## 音视频操作纪律（与 ffmpeg-skill 协作，两 skill 并存互不吞并）

内置配音与媒体校验直接使用本地 ffmpeg/ffprobe，不依赖同级 skill。
其他切片、音频加工和抽帧任务可按需使用 ffmpeg-skill；未安装时不得宣称其检查已执行。
遵循 probe-first → dry-run 规划 → 执行 → verify-after → 抽帧目检。本 skill 内建的最小校验：

- 渲染前:`scripts/check_assignment.py plan.json` 组件归属清零(防"讲到 A 时 B 提前画")
- `render_explainer.py`：校验归属、cue、帧率、画幅、完整解码与时长，再发布输出；失败保留 FAIL 回执，不删除用户原有文件
- `scripts/verify_media.py`：使用本地 ffprobe/ffmpeg 批量校验产物（存在/完整解码/时长±0.75s），不依赖同级 skill；`--metadata-only` 不代表解码通过

```bash
# 例：校验分场音轨与成片（manifest 由管线生成，也可手写）
python scripts/verify_media.py --manifest manifest.json
python scripts/verify_media.py --file 成片.mp4 --expect 462.4
# 环境能力一次性自检（本会话查过就不必重复）
python ../ffmpeg-skill/scripts/_contract.py doctor --json
```

## 故障自检清单（出问题先查这里）

| 症状 | 原因 | 处置 |
|---|---|---|
| **`WSServerHandshakeError 403`（TTS）** | **edge-tts 被微软按 IP/地区封锁** | **重试无用，换 [apiz](https://apiz.ai/)**：`curl -fsSL https://apiz.ai/cli \| sh` → `apiz auth login --api-key sk-...` → 用 `apiz speak --output-file`（**别用 `apiz generate`**）。完整脚本见 `references/apiz-tts-fallback.md` |
| apiz 所有模型都 429 余额不足 | 余额 < 10 元触发全局闸门 | `apiz account balance` 充值，立即恢复 |
| 换配色后成片仍是纯白 | 引擎 `frame_buf = np.full(..., 255)` 硬编码底色 | 用 `--theme`（`lib/themed_render.py` 成片后染色）；底色必须灰度恰好 240 |
| `No such filter: 'tpad'` | ffmpeg 版本老，缺该滤镜 | `theme.patch_no_tpad()`（`render_explainer.py` 已自动调用） |
| 找不到 `ffprobe` | 本机没装 | 自动退回 ffmpeg 解析时长；或改 `lib/theme.py` 的 `FFMPEG_CANDIDATES` |
| `check_assignment` 报未归属且怎么改 box 都不变 | `BW.save()` 收的是**像素** `(x0,y0,x1,y1)` 不是归一化 | 按像素写；**改完 board 必须重跑 `build_narration`**（check 读 plan.json） |
| compose 报 region 引用缺失 | TILE_VISUALS 漏键 / texts 的 key 拼错 | 补键；勿用子串判断"是否已加" |
| 生成块里有乱码假中文/深色底 | 生图提示词约束不够 | 白底占比 <60% 自动重出；提示词强调纯白底+无任何文字 |
| 长音频转写 OOM (mkl_malloc) | 整段推理内存峰值 | 分块转写（transcribe_align 已内置） |
| 模型下载超时/401 | hf.co 被墙 / Xet 协议 | HF_ENDPOINT=hf-mirror.com + HF_HUB_DISABLE_XET=1 |
| 渲染出的 mp4 打不开 | concat 混入了坏分拍 | 删 out/ 整目录重渲（分拍缓存损坏时也删 parts） |
| 视频里出现"方框"字形 | ✗✓ 等 emoji/符号字体缺字 | 用 × √ · 等常规字符 |
| TTS 把 `claw_core` 读成"claw 下划线 core" | edge-tts 对 zh 音色把 `_` 读作"下划线" | 编程标识符的 `_` 一律不读：TTS 前把文本 `_` 替换成空格（参考 esp-claw-course/build_narration_course.py 的 clean() 写法，包一层 tts monkey-patch）。**用户硬性要求（2026-09-17）：涉及代码/技术内容的讲稿，所有旁白 TTS 都要走这个清洗**；已渲染的旧集不必返工 |

## 新一集工作流（先过闸，再制作）

开做前读 **`references/user-gates.md`**。顺序：G0 规格 → G1 风格 → 写稿 → G2 讲稿确认 → 画板 → G3 音色 → TTS → 归属质检 → G4 冒烟 → 全量 → 技术质检 → G5 成片确认。

### 1. 写讲稿 + 拆 region（plan.build.json）

**文章/教程类内容:先按 `references/teaching-script.md` + `user-gates.md` 走完 G1/G2,用户确认讲稿后,再拆 region / 画板。**

每拍 = 一张白板图 + 若干 region（一个 region = 图上一块绘制区域 + 一句 annotation）。**讲稿按 region 子句拆分，每个子句单独 TTS**——分片时长即精确 cue。

```json
{
  "idea": "解释日全食",
  "canvas": [1280, 720],
  "voice": "zh-CN-YunxiNeural",
  "gap": 0.35,
  "scenes": [
    {
      "id": "s01",
      "image": "boards/s01.png",
      "regions": [
        {"label": "title", "box": [10, 330, 125, 670], "annotation": "什么是日全食？"},
        {"label": "body", "box": [130, 80, 820, 720], "annotation": "当月亮恰好完全挡住太阳……"},
        {"label": "deco", "box": [790, 100, 1000, 900]}
      ]
    }
  ]
}
```

无 annotation 的 region = 纯图形（不说话），自动并入与其空间重叠最大的 cue 窗口一起画出；无任何重叠时并入最后一个窗口。

**box 写法**：`[ymin, xmin, ymax, xmax]`，归一化 0–1000（左上原点）。一个 region 也可以给 box 数组（多块同时画）。

### 2. 准备白板底图（三种来源）

| 来源 | 命令 | 说明 |
|---|---|---|
| **PIL 程序化绘制**（几何/图表首选） | 自写脚本，参考 `templates/chart-recipes/eclipse.py` | 几何精确、白底纯净、完全可控 |
| **Agnes 生图**（具象画面） | `python scripts/gen_board_images.py boards.json --out-dir boards` | 免费；prompt 铁律见下 |
| **用户已有图** | 直接放入 boards/ | Excalidraw 导出、教材图等 |

**文字铁律**：AI 只画无字插画（negative 排除 text/letters/Chinese characters）；所有中文/标签/公式用 `make_text_layer.py` 本机字体叠加：

```bash
python scripts/make_text_layer.py boards/s01.png --out boards/s01.png \
  --title "什么是日全食" --title-size 56 \
  --texts texts.json   # 多块文字用 JSON 文件
```

字体跨平台自动探测（Noto CJK / 苹方 / 微软雅黑 / simhei……）；`handwriting` preset 用 skill 自带毛笔字。

**底图硬规则（ink-on-white）**：
- 白底（近白像素引擎会 snap 成白）；灰度 <240 才算墨——浅黄/浅灰要够深（#FFF 系会消失）
- 长边 >1280 引擎自动缩小；项目级画布一次选定（横屏 1280×720 / 竖屏 720×1280）

## 配色主题（换底色/换色系）

引擎把底色**三处硬编码为纯白 255**，实测确认：

```
video_encoding.py:91     white = np.ones((h,w,3), np.uint8) * 255   # 空白帧
video_encoding.py:132    frame_buf = np.full((h,w,3), 255, ...)        # 主帧缓冲
video_encoding.py:178    255.0 + (color - 255.0) * a                  # 淡入混合底色
```

所以**底色只存在于 PNG**：PNG 阶段能通过连通域检查，但像素值进不了视频。
实测把底色从 gray 240 一路加深到 213，成片首帧仍是 `(255,255,255)` 纯白。

解法：**成片后整体染色**（`lib/themed_render.py`）——引擎照常渲染纯白底线稿，
再把「接近纯白」的像素换成主题底色，浅色填充（gray 224~237）原样保留。
不改 site-packages，引擎升级不受影响。

```bash
python scripts/render_explainer.py plan.json --out out/x.mp4 --theme warm
```

或整批换肤：`WHITEBOARD_THEME=cool python ...`

绘图阶段也能切（影响 PNG 里的线条色/填充色/文字色）：

```python
import board_widgets as BW
BW.set_theme("warm")
```

| 主题 | 底色 | 适合 |
|---|---|---|
| `whiteboard` | `#F0F0F0` 近白 | 默认，原有观感，零回归 |
| `warm` | `#FBEDE3` 暖米 | 知识科普、书摘 |
| `cool` | `#EAF1FB` 冷蓝 | 技术/代码讲解 |
| `mint` | `#E7F4F3` 薄荷 | 轻量科普、生活类 |
| `sakura` | `#FBEBED` 樱粉 | 人文、情感、叙事 |

绘图代码**一行不用改**：`BW.set_theme()` 就地改写所有绘图函数的颜色默认值
（函数签名 + 全局常量），52 个函数、40+ 组件的线条色、填充色、文字色全部跟随。

### PNG 阶段的底色约束（仅影响连通域识别，不影响成片底色）

底色必须**灰度恰好 240 的纯色**，否则图形识别会出错：

| 底色灰度 | 引擎行为 |
|---|---|
| 235–239 | ✗ 底色与图形焊成全屏连通域 |
| **240** | ✓ 唯一可用 |
| 241+ | 被刷成纯白 |

**不能用渐变**（跨过 240 即失效）、**不能加噪点**（±3 噪点产生 23606 个连通域）。

改主题表后先体检：

```bash
python lib/tools/check_theme.py          # 底色灰度/误判/文字碎裂/填充色
python lib/tools/pick_paper.py           # 求解任意底色：pick_paper.py "#F0EADC"
python lib/tools/demo_themes.py          # 五主题静态对比图
```

体检会检查一个容易踩的坑：**辅助文字色（`muted`）若与底色同色相且偏浅，小字会被二值化切碎**（实测 `#8496A8` 配 `#EAF1FB` 让 30px 中文碎成 98 块）。所以 `muted` 一律灰度 ≲125 且色相与底色拉开。

### ffmpeg 定位

本机 PATH / 注册表登记的 ffmpeg 目录**已失效**，实际可用的是 ShadowBot 自带那份
（2016 版，有 libx264，**缺 `tpad` 滤镜**）。`lib/theme.py` 的 `ffmpeg_path()`
按 libx264 可用性排好优先级，`setup_ffmpeg_env()` 负责注入 PATH。
缺 `tpad` 的影响：引擎收尾延帧会失败，**渲染时让 `draw_end == total` 即可规避**
（`render_explainer.py` 已按此处理）。

`probe_duration` 也加了兜底：本机没有 `ffprobe`，会自动退回用 ffmpeg 解析时长。

### 3. 生成音轨 + 精确 cue

```bash
python scripts/build_narration.py plan.build.json
```

逐 region 子句 TTS → 分片 → 垫 gap（默认 0.35s）→ concat 成每拍音轨 → 用分片真实时长写出 `plan.json`（regions 带精确 start/end）。edge-tts 偶发 NoAudioReceived，脚本自带重试；**失败的 0 字节分片要删掉重跑**（`find audio/narration/parts -name "*.mp3" -size -2k -delete`）。

### 4. 渲染

```bash
python scripts/render_explainer.py plan.json --out out/<name>.mp4
# 常用：--only s03（单拍调试）  --force（忽略已存在重渲）  --quality high  --dry-run
```

每拍 mp4 输出到 `out/<name>_parts/`，最后 concat。**渲染速度 ≈ 视频时长**（8s 片段约 5-8s）。已存在的分拍自动 skip。

### 5. 验收

- `ffprobe` 成片 video/audio duration 一致
- 每拍抽 1-2 帧：`ffmpeg -i out/parts/s03.mp4 -vf "select=eq(n\,150)" -vframes 1 out/check.png`，确认 cue 对齐（该时刻只有已讲到的元素）
- Windows 下 ffmpeg/Read 图片一律用 `D:/...` 绝对路径（`/d/...` 会失败）

### 6.（可选，用户严格要求才走一步）发布前自检

```bash
python scripts/self_test.py
```

跑三个最小测试：①CRAFT 中文识别 ②白板动画渲染 ③精确 cue 对齐。**任意一个失败就别发版本**。

## Region Plan 硬规则（踩坑总结，必读）

1. **box 紧贴实际内容，不要贪宽**。引擎按"组件 bbox 与 box 交叠 ≥60% 的 box 面积"判定归属；横贯全屏的宽 box 会让大组件被判成"跨多个窗口"（spanning）而归入最早的窗口，打乱绘制顺序。
2. **不同窗口的 box 不要罩住同一个组件**。尤其先画的窗口不要把 box 伸进后画元素的领地。
3. **图上物理相连的元素永远一起画**（连通域不可分割）。想让"本影/半影"分开讲，绘图时必须在它们之间留白缝（≥8px，锥尖附近要更宽——白缝三角形会收敛）。**文字标签必须放在纯白区域**，压在色块上的标签会和色块连成一体。
4. **AI 生图的大色块容易连成巨型连通域**——构图时让主要元素之间留白。
5. cue 窗口装不下绘制量时引擎报 `schedule exceeds cue window`，渲染脚本自动放宽 15%×N 重试，无需手动干预。
6. **每拍第一个 region box 必须罩住标题条**（标题画在 y≈70，归一化后落在约 28–112）。否则标题被引擎挤到最后一个窗口，出现"最后才写标题"。
7. **`check_assignment.py plan.json` 必须 `TOTAL unassigned: 0` 才渲染**。最高频的未归属原因是**画了全宽卡片/横幅却漏写它的 region box**——写 `save(...)` 时就把每个 box 一起写上，别事后补。

## 无删除（safe-delete 钩子）适配

本机存在 safe-delete 钩子，`scope:"turn"` 会**累计整轮的删除次数，达到阈值（50）即拦截该轮后续所有删除**，表现为渲染/构建中途 rc=1。应对：

1. **不要在流水线脚本里 `rm`**。典型事故：`run_ep.sh` 开头的 `rm -f plan.json` 触发拦截 → 直接删掉该行；`build_narration.py` 每次都会覆盖写 `plan.json`，无需预删。
2. **Python 侧**用 `nodel.py`（monkeypatch `pathlib.Path.unlink/rmdir`、`os.remove/unlink/rmdir` 为 no-op）并在 **import 引擎模块之前** `import nodel`；渲染入口用 `render_nodel.py`（`import nodel` 后 `runpy.run_path(render_explainer.py, run_name="__main__")`）。
3. 本机 bash **缺 `dirname`**：流水线脚本里的 `ROOT` 必须**写死绝对路径**（如 `D:/story-skill/<course>`）。

## 常见坑

- **edge-tts 0 字节分片**：NoAudioReceived 后 save 可能留 0 字节文件，重跑会被 skip。先 `find ... -size -2k -delete`；若本机有 safe-delete 钩子，逐个 `rm` 单个 0 字节文件（单次删除不触发阈值）后重跑续传即可，**不要改文案**。
- **`arrow_curve` 的 bend 符号不是绝对上下**：法向偏移 = `(-dy, dx)/L * bend`，方向随起终点符号翻转。画回环 / 绕行箭头必须先算法向，否则会画到反方向并压住元素（s16 的 fail 回路曾画到节点上方）。
- **归属质检未归属的两大高频原因**：①节点之间的箭头落在两个 region 的**缝隙**里（把相邻 region 边界重叠或让箭头整体落进同一 region）；②标签/文字的**尾巴越过 region 边界**（文字实际宽度常比目测宽，用 `text_w` 量一遍再定边界）。判定口径是「组件中心在 box 内 **或** 组件 ≥25% 面积在 box 内」。
- **⭐ 未归属的头号真因是「区域缝」而不是箱子画错**：相邻两个 region box 若**刚好相接**（甚至留几 px 空隙），凡是有组件横跨该边界（箭头、说明行、条带），两个 box 都不完整包含它 → 未归属。**修法：让相邻 region box 边界互相重叠 20~50px，不要刚好相接。** 另：`("label", [(x0,y0,x1,y1)], "")` 这种**极薄的 region + 空旁白**会导致「整卡未归属 + 该窗口无音频」，务必拆成 2~3 个**非空旁白** region。
- **⭐⭐ 写板前必须做字形（豆腐块）预检**：`load_font` 解析到 `C:/Windows/Fonts/msyh.ttc`（微软雅黑），其 cmap **缺 emoji、⛔(U+26D4)、∅(U+2205)、≤、→、✓、✗ 等字形**；PIL 会照常"出墨"画成豆腐框，而**抽帧/验收程序查不出来（有墨就算通过）**。所以：
  1. **板面文字禁用** emoji 与数学/箭头符号，改用中文词（"空集"/"阻塞门"/"小于"）或 **PIL 手绘图形**（✓=两条 `d.line`；↻=`d.arc`+箭头；⊘=红圆+斜杠）。
  2. **落笔前跑一次预检**（需 `pip install fonttools`）：
     ```python
     import sys, io, re
     sys.path.insert(0, r"<skill>/scripts"); import make_text_layer as M
     from fontTools.ttLib import TTFont, TTCollection
     def cmap_of(p):
         try: f = TTCollection(str(p)).fonts[0]
         except Exception: f = TTFont(str(p))
         return set(f.getBestCmap())
     cm = cmap_of(M.resolve_font_path("regular")) | cmap_of(M.resolve_font_path("bold"))
     src = io.open("make_boards.py", encoding="utf-8").read()
     bad = {ch for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', src) for ch in m.group(1)
            if ord(ch) >= 32 and ord(ch) != 0x5C and ord(ch) not in cm}
     print("缺字形:", "".join(sorted(bad)) or "无")
     ```
     注意：正则会把**旁白字符串**也扫进来——旁白里的符号只影响 TTS 朗读，**不算豆腐块**；只需修「被 `BW.text/CW.mtext/box_card/code_card` 画出来」的那些。
- **`CW.*` 命名空间易错点**：横屏课程库里 `text` 是 `BW.text` 的别名（lib 里曾漏掉，写 `CW.text` 会 AttributeError）；`mtext` 是 lib 自定义函数（**不存在** `BW.mtext`）。批量写脚本前先跑一次 `{m for m in re.findall(r"CW\.(\w+)", src) if m not in dir(course_widgets)}` 自检。
- **Windows 路径**：所有 python 脚本内 subprocess 已带 `encoding="utf-8", errors="replace"`；ffmpeg 命令行用 `D:/` 路径不用 `/d/`。
- **进程替换不可用**：`--texts <(echo ...)` 在 Windows Python 下失败，用临时 JSON 文件。
- **concat 要求一致**：所有拍要么全有音轨要么全静音（脚本会强制校验）。
- **Agnes 画手/画笔的先验**：prompt 里出现 "whiteboard/marker" 容易画出手握马克笔的画面，negative 加 `no hands, no pens, no brushes, no people, no tools`。
- **managed python 的 venv 不带 pip**：先 `python -m ensurepip`。
- **AGNES_API_KEY 找不到**：把 `.env` 文件放到 `cwd`、`~/.env`、`~/.workbuddy/.env` 或环境变量任一处均会被读取；缺 key 时 `gen_board_images.py` 会硬报错（不会静默失败）。

## 依赖与凭证

| 依赖 | 类型 | 必须？ |
|---|---|---|
| `whiteboard-animator` | pip 包（PyPI，自带 83MB CRAFT 模型） | 必须，setup 自动 `pip install ==0.1.1` |
| `onnxruntime` / `numpy` / `Pillow` / `opencv` / `scipy` / `scikit-image` | pip 包（引擎传递依赖） | 必须，pip 自动装 |
| `edge-tts` | pip 包 | **可选**——免费 TTS，但常被 403 封锁 |
| `apiz` CLI（[apiz.ai](https://apiz.ai/)） | 系统二进制 | **edge-tts 不可用时替代**，需免费注册拿 key（`curl -fsSL https://apiz.ai/cli | sh`），按量计费 |
| `ffmpeg` | 系统二进制 | 必须，需支持 **libx264**；`ffprobe` 可选（缺了自动退回 ffmpeg 解析时长） |
| `AGNES_API_KEY` | Agnes 生图 API key（可选） | 仅当 `gen_board_images.py` 需要生图时 |

无 `AGNES_API_KEY` 也能出片（PIL 自带的 `make_text_layer.py` + `templates/chart-recipes/*.py` 够画大部分图）；需要 AI 生图时才用它。

## 配套参考

- 完整流水线细节：`references/pipeline.md`
- region plan 写法与坐标纪律：`references/region-plan-guide.md`
- **概念短视频系列七步管线（box 踩坑实录+讲稿骨架）：`references/concept-short-video.md`**
- 共享绘图组件库：`scripts/board_widgets.py`（含组件清单与用法）
- 程序化白板图示例（日全食全套）：`templates/chart-recipes/eclipse.py`
- region plan 示例：`templates/region-plan.example.json`
- 自检脚本：`scripts/self_test.py`
- 教学讲稿流程（文章/教程→视频标准方法）：`references/teaching-script.md`
- 书籍章节→系列短视频（信源纪律/系列规范/TTS重试）：`references/book-chapter-video.md`
- 渲染前归属质检：`python scripts/check_assignment.py plan.json`（0 未归属才渲染）
