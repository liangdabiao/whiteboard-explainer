# 配音可靠性：已实现的任务 1–5

本流程覆盖本地预检、媒体校验、G3 有效配置、旁白缓存和本次音轨/cue 归属。
任务编号指十张任务草案中的 1–5，不是总规格中的工作包 W1–W5。
视频缓存、G4/G5 技术证据与教学停顿见 [render-workflow.md](render-workflow.md)。完整制作遵守 [用户确认协议](user-gates.md)。

## 1. 本地预检

以下命令使用项目虚拟环境解释器运行。从单集目录调用时，将 `<skill>` 替换为 skill 的绝对路径。

```bash
python <skill>/scripts/build_narration.py plan.build.json --dry-run
python <skill>/scripts/build_narration.py plan.build.json --preflight
python <skill>/scripts/build_narration_fast.py plan.build.json --preflight
python <skill>/scripts/gen_tts.py narration.json --preflight
```

- dry-run 验证输入与已存在的画板，输出有效配置；不创建音轨、计划或审批，不联网。运行依赖状态为 `NOTRUN`。
- preflight 额外检查本地 ffmpeg、ffprobe、libx264 与所选 TTS SDK；不调用真实配音，不验证远端连通性。
- 输入须为对象，拍号唯一且不含路径分隔符，box 坐标合法，时长与间隔有限，画板可读取。
- 指定 `font` 时检查字体文件能否加载；这不证明所有汉字、符号和公式字形都完整。
- JSON 无额外解析器依赖；YAML 输入需要依赖清单中的 PyYAML。不会自动安装缺少的包。
- 当前内置入口支持 `edge` / `edge-tts`。不自动切换供应商，也不将失败改记为成功。

## 2. G3 确认实际配置

G0–G2 按既有协议完成后，再由用户在对话中确认 G3。`approve` 打印有效音色、语速、SDK 版本和处理配置；用户回答后再跑 `confirm`。

```bash
# 普通版
python <skill>/scripts/user_gates.py --root . approve G3 --artifact plan.build.json --mode standard
python <skill>/scripts/user_gates.py --root . confirm G3 --note "音色 1 + 语速 A"
python <skill>/scripts/build_narration.py plan.build.json

# 快速版：须单独确认；默认 +22%，且裁首尾静音
python <skill>/scripts/user_gates.py --root . approve G3 --artifact plan.build.json --mode fast
python <skill>/scripts/user_gates.py --root . confirm G3 --note "音色 1 + 快速版 +22%"
python <skill>/scripts/build_narration_fast.py plan.build.json

# 按 scene.text 配音
python <skill>/scripts/user_gates.py --root . approve G3 --artifact narration.json --mode scene
python <skill>/scripts/user_gates.py --root . confirm G3 --note "音色 1"
python <skill>/scripts/gen_tts.py narration.json --out-dir audio/narration
```

- 普通版缺省 `rate` 为 `+0%`，快速版为 `+22%`；输入显式 `rate` 优先。快速版 `--rate` 必须匹配已确认输入。
- 场景配音支持原有 `speed`；未写 `rate` 时折算为百分比。有效值会在预检与审批时展示。
- 改稿、换声、改语速或切换处理配置后，须重新确认 G3。旧版没有有效配置快照的 G3 会被拒绝，不能自动补签。
- region 的 `annotation`、scene 的 `text` 保留画面原文。可用 `spoken_text` 明确指定实际口播；缓存按实际提交文本判定。
- TTS 输入端统一应用已确认读法预处理，版本由有效配置的 `text_version` 记录：版本 2 把 `_` 转为空格并归并空白；画面文本与源讲稿不被修改。
- 单句 `--preview` 仍要求已过 G2，且须先在对话中单独获用户授权；最多一条、100 字，按实际 `spoken_text` 检查。授权写入 `.user-gates.json` 的 `preview` 节，不通过 G3。
- 本轮可靠性保证限于上述内置 CLI。外部 apiz 命令和自定义 monkey-patch 后端不自动获得相同缓存与配置契约。

## 3. 缓存与运行清单

- 原始旁白按实际文本、后端、模型、音色、语速、SDK 与契约版本计算内容指纹。
- 原始合成与裁静音/格式转换分开；仅改变间隔或处理配置时，可以复用相同原始旁白。
- 命中须满足版本、内容指纹、文件哈希和本地完整解码。无元数据、损坏或旧版同名缓存不被信任。
- 旧的 `audio/narration/parts/` 不会自动删除，也不会只因文件同名就复用。
- 共享旁白缓存位于单集目录的 `.narration-cache/`。
- 加工音轨使用 WAV，避免以 MP3 编码填充估算 cue；音轨、cue 和计划归单次运行所有。
- 每次运行在输出目录的 `runs/<配置指纹>/<运行编号>/` 下保存独立产物；不会用新结果覆盖上一运行的音轨。
- 同一项目的配音生产使用本地文件锁。另一个生产者已占用时直接拒绝，避免并发覆写当前计划或重复请求。
- 完成前重新核对输入与画板指纹。中途修改或失败时清单为 `FAIL`，原来的当前计划保持不变。
- 来源内容与哈希从同一次字节读取固定，且与 G3 已批准材料匹配；预检后发现源文件变化时，在合成前中止，不用后读的新稿哈希标记旧文本。
- 配音清单采用 schema 2。schema 1 曾无法证明解析内容与来源哈希一致，即使标为 PASS 也不能升级信任；须重新运行配音入口生成，原始旁白缓存仍按内容复用，旧文件不删除。

`build_narration*` 成功后仍输出根目录 `plan.json`，供现有渲染入口使用：

- `scenes[].audio` 指向本次运行的实际音轨。
- `narration.manifest` 指向本次运行清单；`generated` / `reused` 是本次真实合成和复用次数。
- 清单记录输入与实现指纹、实际音轨及哈希、cue、期望时长和解码结果。
- 运行目录另存可独立解析相对素材路径的计划快照。
- 当前旁白与 cue 通过实际 PCM 计算；hold/尾垫追加静音并向上补齐视频帧，cue 不延伸进停顿。

`gen_tts` 在输出目录保留 `timeline.json` 入口；其中的音轨和清单路径相对于输入项目目录。
每次运行另存自己的 timeline 快照，CLI 输出对应清单与缓存事实。
输入文件不得与生成的 `plan.json` 或 `timeline.json` 重名冲突。

## 4. 独立媒体校验

```bash
python <skill>/scripts/verify_media.py --file audio.wav --kind audio --expect 3.5
python <skill>/scripts/verify_media.py --manifest <本次运行清单>
python <skill>/scripts/verify_media.py --file audio.wav --metadata-only
```

- 使用本地 ffprobe 读取流与有限正时长，使用 ffmpeg 完整解码；不依赖仓库外的辅助 skill。
- `--metadata-only` 明确显示 `decode=NOTRUN`，不能当作完整解码验收。
- 原有数组式 manifest 仍支持；相对路径以 manifest 所在目录解析。
- 版本化配音清单必须为完成状态，计划和音轨哈希必须匹配。不猜测最近目录或同名旧文件。
- `--expect` 必须为有限正数。当前默认时长容差保持原有的 0.75 秒。
- 该工具检查媒体与配音证据，不代表 G4 样片、G5 人工观看或实际中文发音已通过。

## 5. 开发验证

默认测试不请求真实 TTS，也不调用实际白板绘制后端。使用可计数的 SDK 替身、PCM 和彩色帧夹具，经本地 ffmpeg/ffprobe 验证真实编解码、抽帧与时序。
不将这些夹具检查报告为真实中文旁白或完整出片验证。

```bash
python -m unittest discover -s scripts -p "test_*.py" -v
```

关键行为由 CLI 回归覆盖：连续改稿只重配受影响片段、换声失效、raw/加工分离、旧缓存保留、损坏缓存拒绝、失败不替换计划、间隔更新 cue 和生产者冲突。

## 6. 共享配音生产 module

`scripts/narration_production.py` 提供按用途命名的 Python interface。普通版、快速版、场景配音和单句试听共用批准快照、本地预检、生产锁、运行生命周期、归档与发布协议；region/cue 与 `scene.text` 的音轨和计划生成分别保留内部 implementation。

在 `scripts/` 可导入的 Python 环境中调用：

```python
from pathlib import Path
from narration_production import produce_regions, produce_scenes, preview_sentence

# 在现有异步调用环境内执行；普通版缺省 mode="standard"。
plan = await produce_regions(Path("plan.build.json"))
plan = await produce_regions(Path("plan.build.json"), mode="fast")
summary = await produce_scenes(Path("narration.json"), output=Path("audio/narration"))
summary = await preview_sentence(Path("preview.json"), output=Path("preview_audio"))
```

- `produce_regions()` 返回与根目录 `plan.json` 一致的计划。既有 `build(spec, root, dry, mode, rate)` 保留调用方式与返回结构，转交此入口；`dry=True` 仍不申请确认或创建运行。
- `produce_scenes()` 和 `preview_sentence()` 返回本次清单与生成/复用摘要；timeline 仍发布到 `output/timeline.json`，其中音轨和清单路径相对于输入项目目录。
- 直接 Python 调用执行与 CLI 相同的保护。批量配音在 module 内检查 G3；试听在 module 内检查 G2 与单句额外授权，不补签 G3。
- `--design-only`、`--dry-run` 和 `--preflight` 继续复用本地设计与检查逻辑；它们不会通过生产入口请求真实 TTS。
- 归档路径转换与兼容入口发布集中在 module 内。发布失败时尝试记录 `FAIL`，旧入口保持不变；若写入失败回执再次失败，异常链保留原发布错误，不报告成功。
- 配音运行的实现指纹包含此 module；清单继续使用 schema 2，原始旁白缓存仍按原有内容与有效配置判断复用。

回归同时覆盖旧 `build()` 调用和三个用途入口，并验证试听到批量配音的复用、试听授权拒绝、各入口发布失败与失败回执的异常链。SDK adapter 使用离线替身，文件行为使用临时目录，ffmpeg/ffprobe 在本地实际执行。
