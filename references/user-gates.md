# 用户确认闸门（硬性，未确认不得继续）

> 目的：禁止 Agent「一路干到底」。内容、风格、音色必须先让用户选，再进入绘图 / TTS / 渲染。
> 适用范围：本 skill 全部成片任务（单集、系列、文章转视频、深度科普）。
> 用户明确豁免时，只免除对应人工选择或观看；用 `exempt <闸号> --artifact <文件> --scope <豁免范围> --note "<用户原话>"` 交互录入，豁免范围可重复列出；审批绑定与技术检查（G4/G5 回执、媒体完整性）不能豁免。

## 总规则

1. **未获用户明确同意，不得执行**：绘图（`make_boards`）、TTS（`build_narration*` / `build_voice`）、渲染（`render_explainer`）。
2. **每次请用户决定时**：用编号选项；推荐项放第一，标「（推荐）」；每项写动作与后果。
3. **用户改口时**：从被改的那一闸重来；重新生成受影响产物并保留历史副本，不自动删除旧素材。
4. **「70% 即交付」只作用于画面微调**：构图对、元素对即可，不逐拍修图。它**不**允许跳过下列闸门。
5. **确认绑定版本**：每集通过 `scripts/user_gates.py` 保存 `.user-gates.json`，记录确认版本及文件 SHA-256。受保护入口在缺少确认、文件缺失或内容变化时停止。重新确认某闸会清除下游确认。确认在对话中完成，`confirm --note` 必须逐字引用用户原话；口头同意或豁免也必须留记录，不能靠聊天记忆绕过脚本。

## 脚本拦截与操作

每集使用独立项目目录；输入 JSON 放在该目录中。以下示例在集目录内执行，`<skill>` 替换为本 skill 的绝对路径。

确认分两步，全程没有终端弹窗：

1. `approve` 冻结并打印待确认内容，**不写** `.user-gates.json`。Agent 把打印结果原样贴进对话，请用户确认。
2. 用户在对话中回答后，Agent 跑 `confirm`，把用户原话用 `--note` 逐字传入。脚本据此写入 `.user-gates.json`。

用户拒绝或改口时，用 `discard <闸号>` 丢弃暂存内容，不要 `confirm`。待确认文件在确认或丢弃前一直留在 `.user-gates.pending.json`；其间任何文件变化都会让 `confirm` 失败，必须重跑 `approve`。暂存与确认共用审批锁；另一个生产者在暂存或确认期间持锁时，`approve` 直接失败而不是覆盖暂存内容。

```bash
# G0 可声明选用能力并检查本地条件（只查存在性，不试连、不打印密钥值）：
python <skill>/scripts/user_gates.py --root . approve G0 --artifact task.md --capability boards --capability render
python <skill>/scripts/user_gates.py --root . confirm G0 --note "用户原话"
python <skill>/scripts/user_gates.py --root . approve G1 --artifact style.md
python <skill>/scripts/user_gates.py --root . confirm G1 --note "用户原话"
python <skill>/scripts/user_gates.py --root . approve G2 --artifact 讲稿.md
python <skill>/scripts/user_gates.py --root . confirm G2 --note "讲稿确认，可以画"
# 自定义 PIL 绘图也必须经此入口运行：
python <skill>/scripts/user_gates.py --root . run boards -- python make_boards.py
# G3 必须绑定实际配音输入；快速版 rate 写入 plan.build.json，并与 --rate 一致：
python <skill>/scripts/user_gates.py --root . approve G3 --artifact plan.build.json --mode fast
python <skill>/scripts/user_gates.py --root . confirm G3 --note "音色 1 + 语速 A"
python <skill>/scripts/build_narration_fast.py plan.build.json
python <skill>/scripts/render_explainer.py plan.json --out out/video.mp4 --only s01
# 用户看过单拍与抽帧后，使用 REPORT.receipt 的实际路径：
python <skill>/scripts/user_gates.py --root . approve G4 --artifact <sample.json路径>
python <skill>/scripts/user_gates.py --root . confirm G4 --note "样片没问题"
python <skill>/scripts/render_explainer.py plan.json --out out/video.mp4
# 用户完整观看后，确认全量运行的类型化回执：
python <skill>/scripts/user_gates.py --root . approve G5 --artifact <render.json路径>
python <skill>/scripts/user_gates.py --root . confirm G5 --note "成片确认，可以交付"
python <skill>/scripts/user_gates.py --root . check G5 --artifact out/video.mp4
```

- 内建拦截：`gen_board_images.py` 要求 G2；`make_text_layer.py` 要求当前目录（或 `--project-root`）的 G2；两个 `build_narration` CLI 和 `gen_tts.py` 批量模式要求 G3 且绑定当前输入与有效配置；渲染单拍要求 G3，全量要求 G4 且绑定当前 `plan.json`。共享 `build()` 也检查 G3 和实际输入内容。
- G3 的 `--mode standard`、`--mode fast`、`--mode scene` 分别对应普通版、快速版和场景配音。旧 G3 没有有效配置快照时须重新确认。预检、缓存与配音清单操作见 [narration-workflow.md](narration-workflow.md)。
- 审批 JSON 含场景 `image` / `audio` 时，同时记录引用文件的哈希。后续改变画板或音频也会使确认失效。
- 支持 `--dry-run` 的入口在该模式下不要求确认。G3 前的单句探测用 `gen_tts.py preview.yaml --preview --out-dir <试听目录>`；YAML 只能有一条非空、至多 100 字的文本，且需已过 G2。用户须先在对话中单独授权这句试听，`--preview` 不弹窗，只把授权写入 `.user-gates.json` 的 `preview` 节留审计；该授权不通过 G3。YAML 解析依赖 `requirements.txt` 中的 PyYAML。
- 自定义 `build_voice.py`、外部 apiz 和其他制作程序必须用 `user_gates.py run tts -- <命令>` 包裹；自定义单拍渲染用 `run sample`（要求 G3），自定义全量渲染用 `run render`（要求 G4），自定义交付命令用 `run deliver`（要求 G5）。只有受保护入口和该包装器执行拦截，直接调用外部工具不受控制。
- G4/G5 强制验证样片/全量回执类型、方案、产物和必要检查。教学设计、视频缓存和回执迁移见 [render-workflow.md](render-workflow.md)。
- 这不是安全沙箱。能改脚本或审批文件的人仍能绕过；哈希不能证明用户实际观看，也不能自动核对教学语义。写稿与人工观看仍须遵守协议。

## 闸门总表

| 闸号 | 名称 | 时机 | 交给用户的产物 | 通过条件 | 通过后才可做 |
|---|---|---|---|---|---|
| G0 | 任务规格 | 动手前 | 画幅、系列类型、成片目标时长 | 用户选定或确认默认 | 抓原文 / 写稿 |
| G1 | 讲稿风格 | 写完整讲稿前（可与覆盖度清单同轮） | 风格选项（见下） | 用户选定一种风格 | 按该风格写 `讲稿.md` |
| G2 | 讲稿内容 | `讲稿.md` 自检完成后 | 完整讲稿 + 自检勾选结果 + 覆盖度清单 | 用户明确说「讲稿确认 / 可以画」 | 写 `make_boards.py`、出图 |
| G3 | TTS 语音 | 讲稿确认后、跑 TTS 前 | 后端 + 音色 + 语速选项；可选试听一句 | 用户选定 voice（与可选 rate） | `build_narration*` / `build_voice` |
| G4 | 冒烟一拍 | 全量渲染前 | 单拍、两张抽帧与 sample.json | 用户确认并记录该次回执 | 同方案全量渲染 |
| G5 | 最终成片 | 全量渲染和技术质检后 | 完整视频、render.json 与已知问题 | 必要检查通过，用户确认或明确豁免后记录 | 标记交付完成 |

系列量产时：**每一集**都过 G2→G5；G0/G1 可在系列开头确认一次，换风格或换音色时重开。

---

## G1 讲稿风格（必须让用户选）

写稿前把下表贴给用户，等选定后再写 `讲稿.md`。

| 编号 | 风格 | 旁白怎么写 | 白板怎么画 | 适合 |
|---|---|---|---|---|
| 1（推荐） | **一问一答** | 每拍旁白标角色：`问：` / `答：`（或 `学员：` / `老师：`）。问句短，答句给事实与例子。允许同拍内先问后答（两个 region）。 | 问句配 Q 气泡；答句配图解 / 代码卡 / 实例条。 | 概念科普、教程、怕单调的独白 |
| 2 | 独白讲解 | 单一叙述者，问题驱动仍要有，但旁白不换角色。 | 可有 Q 气泡，旁白仍是一人讲。 | 短资讯、节奏极快 |
| 3 | 苏格拉底追问 | 连续 2～3 个追问 region，再给结论 region。 | 多个 Q 气泡递进，最后揭晓。 | 反直觉、易误解的主题 |

### 一问一答写法（选定风格 1 时强制）

`讲稿.md` 逐拍表增加「角色」列，或在旁白列内用前缀：

```markdown
| 拍 | 画面 | 角色 | 旁白 |
|---|---|---|---|
| s03a | Q 气泡「波特率乱了会怎样？」 | 问 | 如果收发双方波特率对不上，会发生什么？ |
| s03b | 帧错位示意图 | 答 | 采样点会偏到邻位，整帧数据全错。 |
```

- 问句 region 的 `annotation` 只写问句；答句 region 只写答句。不要把问答揉进同一句 TTS。
- 双音色（可选）：用户在 G3 可再选「问用音色 A、答用音色 B」。未选则同一音色，靠文案与画面区分角色。
- 启发点、覆盖度、单拍 ≤50 字等规则不变；问答只改叙述形态，不减知识点。

---

## G2 讲稿内容确认（必须停）

Agent 在自检通过后，**停下来**发出确认请求，模板如下（可删无的节）：

```markdown
请确认讲稿后再继续。未确认前我不会画板、不会配音、不会渲染。

**风格**：<G1 已选>
**预计**：约 <N> 拍，旁白约 <字数> 字，成片约 <分钟>（按语速估算）

**覆盖度**：<已勾 / 总项>；未覆盖：<无则写「无」>
**自检**：覆盖度 / 准确性 / 问题链 / 例子密度 / 启发点 / 节奏 — 逐项写「通过」或「待改：…」

完整讲稿见：`讲稿.md`

1. 讲稿确认，可以进入画板（推荐）— 下一步做 make_boards。
2. 修改讲稿 — 请指出拍号与改法；我改完再送确认。
3. 换风格重写 — 回到 G1。
```

用户只回「继续 / OK / 做吧」且未提修改时，视为通过 G2。用户提出具体修改时，改完必须再次送确认。

重要篇章（多章、系列、用户标明「重要」的集）：G2 必须附上**分章/分拍摘要**（每章 3～5 条要点），不得只丢文件路径。

---

## G3 TTS 语音风格确认（必须停）

讲稿确认后，先请求用户授权后端探测。G3 确认前仅可在单独获准后合成一句探测或试听，不得批量配音；付费后端须先说明费用并获准。探测命令：

```bash
python scripts/gen_tts.py preview.yaml --preview --out-dir preview_audio
```

- 成功 → 后端 = edge-tts
- `403` / 失败 → 后端 = apiz（见 `apiz-tts-fallback.md`），并如实告知

### edge-tts 常用选项（中文）

| 编号 | voice | 听感 | 备注 |
|---|---|---|---|
| 1（推荐·男） | `zh-CN-YunxiNeural` | 沉稳男声 | 科普/技术常用 |
| 2（推荐·女） | `zh-CN-XiaoyiNeural` | 清亮女声 | `gen_tts.py` 默认女声 |
| 3 | `zh-CN-XiaoxiaoNeural` | 明亮女声 | 偏活泼 |
| 4 | `zh-CN-YunyangNeural` | 播音男声 | 偏正式 |

语速（写入 `plan.build.json` 的 `rate`，与配音有效配置一致）：

| 编号 | rate | 后果 |
|---|---|---|
| A（推荐） | `+22%` | 更紧凑，约省 20% 时长 |
| B | `+15%` | 更稳 |
| C | `+0%` | 原速 |

### apiz 常用选项（中文讲解）

| 编号 | voice | 听感 |
|---|---|---|
| 1（推荐） | `Chinese (Mandarin)_Warm_Bestie` | 温暖，长篇不累 |
| 2 | `Chinese (Mandarin)_Gentleman` | 温润男声，历史/科普 |

更多音色：`apiz voices list --json`（筛 `tags` 含「中文」）。速度用 `--speed`（如 `1.22` ≈ +22%）。

### 一问一答 + 双音色（可选）

用户选风格 1 时，追加问：

```markdown
问答配音：
1. 同一音色（推荐）— 实现简单，靠文案区分。
2. 双音色 — 请指定「问」与「答」各一个 voice；实现上分 role 调用 TTS。
```

### G3 确认模板

```markdown
请选择旁白语音。未确认前我不会跑 TTS。

**后端**：<edge-tts | apiz>（探测结果）
**风格**：<G1>

1. <voice 名>（推荐）— <听感>
2. …
语速：A +22%（推荐） / B +15% / C +0%
试听：需要的话我用选定音色合成一句样例再定。

请回复例如：`音色 1 + 语速 A`。
```

把选定的 `voice` / rate 写入 `plan.build.json` 再跑配音；自定义配音程序用 `run tts` 包裹并沿用同一配置。

---

## G4 冒烟确认（全量前）

```bash
python scripts/render_explainer.py plan.json --out out/<name>.mp4 --only s01
# CLI 自动生成样片、两张抽帧与 sample.json
```

请用户看样片与抽帧：cue 顺序、有无提前画出未讲元素。用户通过后，用 `approve G4` 打印的内容在对话中确认，再 `confirm G4 --note "<用户原话>"` 记录该次 sample.json，才能按同一配置全量渲染。

---

## G5 最终成片确认（交付前必须停）

全量渲染后，先完成技术质检，再送用户确认：

1. 用 `verify_media.py --manifest <render.json路径>` 检查当前全量回执；提供实际时长、预期时长和检查结果。检查失败时先修复；未执行的检查不得称为通过。
2. 提供当前版本的完整视频路径或可播放链接，请用户完整观看。抽帧或 G4 单拍确认不能替代完整视频确认。
3. 请用户检查：知识点有无漏讲、文字有无错字或缺字、发音是否正确、音量和停顿是否合适、绘制是否与旁白同步、开头结尾是否完整。
4. 停下来等待确认。用户提出修改时，记录时间点或拍号，返回对应闸门；重做受影响产物并重新质检、提交 G5。技术检查失败不能用用户豁免改写成通过。

```markdown
请确认最终成片。当前版本尚未完成用户验收。

**视频**：<当前版本路径或链接>
**时长**：实际 <秒> / 预期 <秒>
**技术质检**：<已验证的检查与结果；未验证项及原因>
**已知问题**：<问题清单，无则写「无」>

请完整观看，检查漏讲、错字、发音、音量、音画同步和开头结尾。

1. 当前版本成片通过，可以交付（推荐）— 记录确认版本后完成交付。
2. 修改成片 — 请提供时间点或拍号及问题；修改后重新提交确认。
```

未获确认或明确豁免时，只能报告「成片已生成，等待 G5 确认」。随后仍须 `approve G5` 后由 Agent 跑 `confirm G5 --note "<用户原话>"`，不能用口头回复或说明文件替代技术证据。

---

## Agent 自检（每次开做前）

- [ ] 已读本文件，并按任务类型读对应管线文档
- [ ] G1 已有用户选定风格（或本轮有效豁免）
- [ ] G2 已有用户确认讲稿（或本轮有效豁免）
- [ ] G3 已有用户选定 voice/rate（或本轮有效豁免）
- [ ] 未确认状态下，本回合没有调用 make_boards / TTS / 全量 render
- [ ] 全量渲染前已有 G4 确认；标记交付完成前已有当前版本的 G5 确认（或对应的明确豁免）

任一项未勾且无豁免 → **停，先发确认请求，不得继续制作。**
