# whiteboard-explainer 工作约定

本文件适用于本仓库内的开发、审查和视频制作。交流、工作文档与提交说明默认使用中文。

## 项目与目录

本项目是 Python 白板讲解视频 skill，不是 Web 应用。保留像素级逐笔绘制和 region/cue 音画对齐，不因对标其他项目而替换渲染路线。

| 位置 | 职责 |
|---|---|
| `SKILL.md` | 制作入口、任务分流与制作纪律 |
| `references/` | 用户确认协议、分类型制作流程与改造规格 |
| `scripts/` | 绘图、配音、渲染、审批及检查 CLI |
| `lib/` | 主题、绘图审计及服务客户端 |
| `templates/` | 制作计划示例和图解配方 |
| `assets/`、`vendor/` | 字体资产与第三方归属说明 |

术语沿用项目现有表达：“拍”是一个制作单元，“region”是绘制区域，“cue”是区域的绘制时间窗。不要把教学角色、绘图组件和渲染主题混为一谈。

## 开始任务前

1. 检查 `git status --short`，区分既有改动与本次改动。保留用户文件和不明来源目录，不把 `.statamcp/` 纳入无关变更。
2. 开发时读取目标模块、调用方和相关测试；制作视频时先读 `SKILL.md` 与 `references/user-gates.md`。
3. 文章或教程转视频时读 `references/teaching-script.md`；系列、书籍或深度科普按 `SKILL.md` 的分流指针读取对应流程。
4. 修改缓存、审批或验收机制时读 `references/production-reliability-spec.md`。该文件是待实现规格，不能作为功能已经存在的证明。

## 视频制作与用户确认

- 按 `references/user-gates.md` 执行 G0–G5。不得把开发任务授权当作绘图、配音或全量渲染授权。
- 先确认讲稿与音色，再制作；先提交单拍样片，再全量渲染；最后提交完整成片与实际检查结果。
- 审批入口是 `scripts/user_gates.py`，每集使用独立目录和 `.user-gates.json`。用户在对话中确认：Agent 跑 `approve` 打印待确认内容，用户回答后 Agent 跑 `confirm --note "<用户原话>"`。Agent 不得替用户作答、编造用户原话或伪造审批文件。
- 自定义绘图、配音和交付命令按协议使用审批包装器；单句探测或试听也须单独获准。
- 用户豁免人工确认时记录豁免范围；不得把豁免当作技术检查通过。
- 当前审批不是安全沙箱。G4/G5 必须绑定当前类型化回执和产物；脚本不能证明用户实际观看或教学语义正确。

## 开发与已知限制

- 优先修改共享根因，复用现有函数与 CLI，不为单个问题另造一套制作框架。
- 新增非平凡逻辑时补行为回归测试。重点测试“制作一次、改变输入、再次制作”，不只测试首次执行。
- 内置配音和视频均按内容及有效配置复用；操作与迁移见 `references/narration-workflow.md`、`references/render-workflow.md`。
- 默认渲染会执行组件归属和 cue 检查；无 region 或无显式 cue 时明确记录 SKIP，不宣称精确语音对齐。
- `verify_media.py` 使用本地 ffprobe 与 ffmpeg，默认完整解码；`--metadata-only` 不证明解码通过。失败或未执行时不得报告媒体验收通过。
- `self_test.py` 现有通过条件不能证明真实音画对齐。对齐结论须有相应时间窗的画面证据。
- 更新制作规则时同步相关入口文档，但详细规则保留在权威文件，不在多个位置复制完整流程。
- 不直接修改虚拟环境中的第三方源码；遵循现有主题与兼容处理边界。

## 环境与验证

依赖以 `requirements.txt` 为准。使用项目虚拟环境，网络安装与收费服务调用须先获准。
渲染依赖支持 libx264 的 ffmpeg；媒体检查还须核对实际可用的探测能力。

从仓库根目录执行离线审批回归：

```bash
# Windows / Git Bash
.venv/Scripts/python.exe -m unittest discover -s scripts -p "test_*.py" -v
git diff --check
```

macOS/Linux 使用 `.venv/bin/python` 替换解释器路径。其他测试按本次修改范围选择，不将以上命令当作完整出片验收。

- 用临时目录和替身 TTS/渲染器测试流程，默认不请求真实服务。
- `scripts/self_test.py` 会绘图并渲染视频，不能当作无副作用的普通单元测试自动执行。
- 报告区分代码修改完成、离线测试通过、真实渲染通过和人工观看确认。每个结论只覆盖实际执行的检查。

## 文件、凭证与许可

- 用户成片与中间产物放在明确的单集目录；不提交虚拟环境、音频、视频、缓存、审批记录或密钥。
- 不覆盖或清理用户既有素材。删除、重建或替换既有产物前说明范围并取得授权。
- 不打印 `.env`、API key 或带 token 的 URL。查询配置时只报告所需字段是否存在。
- 复制第三方代码前读许可证并保留归属；模型和字体许可单独核对，不能因本 skill 许可而推断所有依赖都可商用。参见 `vendor/ATTRIBUTION.md`。

## Git 与远程操作

- 仅在用户明确要求时执行 `git add`、`commit` 或 `push`；一次授权不延伸到后续任务。
- 本项目工作仓库是 `jefeerzhang/whiteboard-explainer`，原作者仓库是 upstream。GitHub 命令显式指定 `--repo jefeerzhang/whiteboard-explainer`，避免默认远程解析到上游。
- 提交采用中文 Conventional Commits：`type(中文范围): 中文动宾短语`。标题简述不超过 50 字符，正文说明原因、方案与影响；不兼容变更写明迁移方法。
- 不自动开启 Issues、创建标签、发布 Issue、关闭需求或更改仓库设置；先核对目标并取得对应授权。

## Agent skills

### Issue tracker

需求与规格使用 `jefeerzhang/whiteboard-explainer` 的 GitHub Issues。
操作规则见 `docs/agents/issue-tracker.md`。
GitHub 命令必须显式指定本仓库，避免误操作 upstream。

### Triage labels

使用五个默认分流标签。
角色映射见 `docs/agents/triage-labels.md`。

### Domain docs

采用单一领域上下文：根目录 `GLOSSARY.md` 与 `docs/adr/`。
读取和维护规则见 `docs/agents/domain.md`。
