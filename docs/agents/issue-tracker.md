# Issue tracker: GitHub

本仓库的需求与规格记录在 `jefeerzhang/whiteboard-explainer` 的 GitHub Issues。使用 `gh` CLI 操作。

## 仓库定位

每条命令显式指定 `--repo jefeerzhang/whiteboard-explainer`。
不得依赖默认远程解析，不得向 upstream 或 `class2026` 发布。

## 常用操作

```bash
# 创建
gh issue create --repo jefeerzhang/whiteboard-explainer --title "标题" --body-file "正文文件"

# 读取
gh issue view <编号> --repo jefeerzhang/whiteboard-explainer --json number,title,body,labels,comments

# 列出
gh issue list --repo jefeerzhang/whiteboard-explainer --state open --json number,title,body,labels

# 添加标签；移除时改用 --remove-label
gh issue edit <编号> --repo jefeerzhang/whiteboard-explainer --add-label "<标签>"

# 评论
gh issue comment <编号> --repo jefeerzhang/whiteboard-explainer --body-file "评论文件"

# 关闭
gh issue close <编号> --repo jefeerzhang/whiteboard-explainer --comment "关闭原因"
```

## 发布与依赖

技能要求“发布到 tracker”时，创建 GitHub Issue。
提交 Markdown 文件不等于发布 Issue。

父子任务优先使用 GitHub 原生子 Issue。
阻塞关系优先使用原生 issue dependencies。
功能不可用时，在正文明确写 `Part of #编号`、`Blocked by: #编号`。

规格发布使用 `ready-for-agent` 标签。
标签含义见 [triage-labels.md](triage-labels.md)。
不得在没有对应请求时批量修改或关闭既有 Issue。

## Pull requests as a triage surface

PRs as a request surface: no.
