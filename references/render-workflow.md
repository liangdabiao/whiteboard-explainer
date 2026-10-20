# 视频缓存、确认回执与教学停顿

本流程对应任务草案 6–10，与 [配音流程](narration-workflow.md) 共同组成制作路径。
技术检查不证明用户实际观看，也不自动判断教学内容、中文发音或绘图是否符合审美要求。

## 1. 从单拍到交付

从单集目录执行，`<skill>` 替换为本 skill 的绝对路径。
G0–G3 按 [用户确认协议](user-gates.md) 完成后：

```bash
python <skill>/scripts/render_explainer.py plan.json --out out/video.mp4 --only s01
```

CLI 末行 `REPORT` 是 JSON，提供 `output`、`receipt`、`checks` 和 `video_cache`。
单拍回执是 `.render-runs/<方案指纹>/<运行编号>/sample.json`。
该目录同时保存样片和两张抽帧。先看视频和抽帧，再在对话中确认：

```bash
python <skill>/scripts/user_gates.py --root . approve G4 --artifact <sample.json路径>
python <skill>/scripts/user_gates.py --root . confirm G4 --note "样片没问题"
python <skill>/scripts/render_explainer.py plan.json --out out/video.mp4
```

全量执行必须使用与样片一致的计划、素材、主题、画幅、质量与帧率。
全量末行 `REPORT.receipt` 指向 `render.json`；它绑定完整视频、当前输出文件与检查结果。

```bash
python <skill>/scripts/verify_media.py --manifest <render.json路径>
# 用户完整观看后：
python <skill>/scripts/user_gates.py --root . approve G5 --artifact <render.json路径>
python <skill>/scripts/user_gates.py --root . confirm G5 --note "成片确认，可以交付"
python <skill>/scripts/user_gates.py --root . check G5 --artifact out/video.mp4
```

- G4 只接受完成的单拍回执；G5 只接受完成的全量回执。
- 任意说明文件、手写 `PASS` 或把单拍回执用于 G5，均不能通过。
- 回执校验重新检查素材、实现指纹、成片哈希、视频流、尺寸、fps、完整解码与时长。
- 回执写入与读取共用检查状态、拍选择和产物角色约束。样片必须有一个样片视频和两张抽帧；全量必须有一个运行视频及内容一致的交付文件。缺项、重复产物路径或使用其他阶段的角色都会失败。
- 当前输出必须与不可变运行副本一致；修改或删除输出会使交付检查失败。
- 回执中的视频缓存数量是本次分拍的生成/复用事实，不代表没有执行拼接、解码和校验。
- 输入或实现变化后须重新生成样片并确认 G4；重新确认会清除下游确认。
- 确认时使用文件锁，并核对等待期间的上一闸版本；并发改口不会被旧确认覆盖。
- `approve` 与 `confirm` 之间有延迟时，任一受审文件或回执变化都会让 `confirm` 失败，必须重跑 `approve`。
- Agent 只能把用户真实说过的话写进 `--note`；不得替用户作答或编造原话。测试夹具中的替身确认不能用于交付。

## 2. 缓存、目录与覆盖规则

- `.video-cache/` 保存按内容指纹命名的分拍和元数据。不再按 `s01.mp4` 是否存在决定跳过。
- 指纹包含画板、音轨、cue、有效主题/画幅/fps/质量和实现、引擎版本。
- 命中前核对文件哈希、完整解码、音轨、fps、尺寸和分拍时长；损坏缓存不复用。
- 渲染中输入变化时拒绝发布缓存；运行结束前再次核对完整方案。
- `.render-runs/` 保存独立的运行视频、抽帧与回执；失败保留 `FAIL` 回执，不把它当交付证据。
- 现有输出不会无提示覆盖。使用新输出路径，或在用户明确决定后加 `--force`。
- `--force` 重新渲染分拍并允许替换当前输出，但历史运行副本不删除。
- 同一输出的写入持有文件锁；竞争生产者被拒绝，取得锁后还会复查输出是否已存在。
- 输出须为 MP4。原有 `_parts/s01.mp4` 只作为旧产物保留，不迁移成可信缓存。
- 旧 G4/G5 记录没有类型化回执时须重新走样片与验收，不能自动补签。
- 配音清单须使用 schema 2 并记录固定的已批准输入快照；旧 schema 1 或缺少来源时重跑内置配音入口，可复用仍有效的原始旁白。不得手工改版本号或 PASS 状态代替重新生成。

画幅优先使用 `plan.canvas`；未提供时按第一张画板推导，最长边限制为 1280，并采用偶数像素。
显式画幅须为 2–1280 范围的两个偶数。画板按目标画幅缩放，不自动重排文本；改变版式时应重绘。
组件归属检查使用与渲染相同的白底合成与缩放结果，避免检查和实际画面采用不同几何。

## 3. 四态检查

| 状态 | 含义 |
|---|---|
| PASS | 对本次输入或输出实际检查通过 |
| FAIL | 实际检查或对应制作阶段失败 |
| SKIP | 明确不适用，例如没有 region 时的组件归属 |
| NOTRUN | 未执行，包含前置阶段失败导致后续未运行 |

`REPORT.checks` 包含输入、组件归属、cue、渲染、媒体、时长；`REPORT.check_evidence` 记录每项已执行检查的运行标识、检查方法与证据。
无显式 cue 时，cue 状态为 SKIP；全部有 region 的拍都是精确 cue 才记 PASS；部分拍估算时记 FAIL，不宣称整体精确对齐。
有显式 cue 时检查有限值、起止配对及场景边界；精确 cue 渲染失败不会悄悄放宽时间窗。
失败按 PREFLIGHT、RENDER、VERIFY 阶段返回非零码，后续检查保留 NOTRUN。
回执是技术证据，不等于所有可感知音画同步或教学语义已经自动验证。

单独的 `verify_media.py --file` 仍支持元数据检查；`--metadata-only` 不证明完整解码。
验证完整渲染回执时必须完整解码，不能与单文件、期望时长或元数据跳过选项混用。

## 4. 可选教学画面计划

普通科普默认不启用教学模式，不强制练习、答案或固定教学弧。
启用时，在输入顶层写 `"teaching": true`，每拍写：

```json
{
  "role": "rule",
  "visual": {
    "form": "structure",
    "objects": ["原因", "结果"],
    "change": "先展示原因，再连接到结果",
    "outcome": "原因指向结果的连线完成",
    "order": ["原因", "结果"]
  }
}
```

- `role`：title、rule、example、mistake、practice、answer、summary。
- `form`：text、structure、steps、compare、formula、chart。
- `objects`：1–6 个不同对象；`order` 恰好排列这些对象；`change` 描述变化或静态关系；`outcome` 说明画面最终呈现的结果。
- 题目 practice 后紧接 answer，答案也须紧跟对应题目；不强制所有讲解都有练习。
- 教学角色、画面形式和主题分别表达学习目的、知识关系与配色字体，不互相替代。
- 这些字段用于设计确认和一致性校验，不是新的自动排版或绘图后端；实际画板仍须按计划制作并人工核对。

G2 必须先于绘图。用不读取画板、不请求 SDK 的设计输出解决这个先后关系：

```bash
python <skill>/scripts/build_narration.py plan.build.json --design-only > design.json
python <skill>/scripts/user_gates.py --root . approve G2 --artifact 讲稿.md --artifact design.json
python <skill>/scripts/user_gates.py --root . confirm G2 --note "讲稿确认，可以画"
```

上述为 Bash 重定向示例；Windows PowerShell 可用 `... --design-only | Set-Content -Encoding utf8 design.json`，避免保存成 UTF-16。

设计输出包含原始旁白、角色、形式、对象和顺序。G3 和渲染入口会核对其是否已由 G2 确认。
改变设计或正文后重新确认 G2；仅换音色或读法时仍由 G3 确认，不篡改画面原文。
设计身份统一 `hold` 的整数/浮点表示和空旁白槽位；省略 region 与空文本不会凭表示差异被当作改稿。
按旧表示法指纹记录的 G2 不再自动折算；旧记录须按当前统一身份重新 approve 并 confirm G2。

## 5. 停顿与帧锁

- 在 practice 拍写 `hold`，范围为 0–120 秒；0 和 5 均可。未声明教学模式不能偷偷启用思考停顿。
- 顶层 `fps` 为 1–120 的整数，缺省 24；可选 `tail_pad` 为 0–120 秒。
- 原始合成缓存不含 hold/fps；修改这些值只更新加工音轨、cue 与运行清单，不重新合成未变旁白。
- 根据实际 PCM 样本数计算活动时长，追加零样本静音，再向上补足视频帧边界；不裁旁白。
- 无旁白的插页可生成静音音轨，保持拼接流一致；静音板书的活动时长取该拍 duration，缺省 8 秒。
- 生成计划记录 narration_duration、hold、tail_pad、fps、frames。cue 只覆盖活动区间，不延伸进思考停顿。
- 有 hold/尾垫时，引擎只生成活动片段，之后重复当前片段末帧；不会在停顿期间开始绘制下一拍答案。
- 内置配音已按帧锁定时，渲染 fps 必须一致。改 fps 后重新生成计划与加工音轨，再确认新 G4。

## 6. 验证范围

离线测试在制作 CLI 边界使用替身 TTS 和确定性绘制替身；本地 ffmpeg/ffprobe 实际编码、抽帧与解码。
彩色帧夹具验证停顿画面冻结和答案出现顺序；PCM 夹具验证静音样本与帧边界。
这些测试不等于真实中文发音、实际 CRAFT 逐笔绘制、复杂图形完成度或最终用户观看验收。
真实制作仍须走 G0–G5，不能拿开发测试结果代替人工确认。

任务 1–10 初次开发验证为 57 项。针对审批表示差异与输入快照竞态修复后，完整离线测试 69 项通过，相关模块通过 mypy 和语法检查。
其中包含 20/24/29 fps 的音频或视频边界夹具；没有请求真实 TTS，也没有运行真实白板逐笔绘制验收。

## 7. 共享渲染回执 module

`scripts/render_contract.py` 中的 `RenderReceipt` 管理单次渲染回执，集中检查状态推进、失败阶段、缓存事实、产物登记与回执发布。`render_explainer.py` 继续负责绘制、拼接与抽帧，不再拼装回执字典或根据该字典推断失败阶段。

- 检查开始时记为 `FAIL`，正常返回后才记为 `PASS`；未开始的后续检查保持 `NOTRUN`。归属与 cue 的 `SKIP` 仍按完整方案判定。
- 运行视频必须通过实际解码、画幅、帧率和时长校验。完成回执前再次核对输入快照，转换产物相对路径并检查对应阶段的完整性。
- 回执使用 schema 2：除检查状态外，每项已执行检查附运行标识、检查方法与证据（`check_evidence`）。schema 1 回执缺少这些字段，须重新生成样片并确认，不自动补签 G4/G5。代码修改仍按既有实现指纹机制使旧方案失效。
- 写入 `PASS` 回执失败时，仅尝试保存 `FAIL` 回执；若失败回执也无法写入，异常继续向上传递，不报告成功。当前输出的原子替换失败时，旧输出保持不变。
- 审批与独立媒体验收仍调用 `validate_evidence()`。该入口消费相同结构约束，但重新读取文件、核对哈希并完整解码，不把写端的 `PASS` 当作复验结果。

文件操作使用真实临时目录验证；绘制器与 TTS 使用替身，ffmpeg/ffprobe 在本地实际执行。回归覆盖检查阶段失败、回执写入失败、交付发布失败、重复或错误角色产物，以及视频损坏后同步改写哈希仍不能通过解码检查。
