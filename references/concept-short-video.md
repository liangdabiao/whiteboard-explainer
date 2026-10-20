# 概念短视频系列（文章 → 白板讲解，标准管线）

> 从《5分钟商学院》EP1《人人都应该是自己的CEO》全流程验证（2026-09-13）。
> 适用：商业/心理/经济概念科普系列短视频，一篇文章一集，竖屏 720×1280。
> 本文档是「教学讲稿流程 (teaching-script.md)」在**系列化量产**场景的落地版，两者原则一致。
>
> **硬性叠加**：[`user-gates.md`](user-gates.md)。系列开头确认 G0/G1/G3；**每一集**在画板前过 G2，全量渲染前过 G4。未确认不得制作。

## 成片规格（已验证基线）

- 竖屏 720×1280，24fps H.264，AAC 音轨；成片 1.5~2.5 分钟，14 拍左右，每拍 2~5 个 region
- 旁白 zh-CN-YunxiNeural **+22% 语速**（build_narration_fast.py，自动裁首尾静音），gap 0.2s
- 渲染：render_explainer.py 精确 cue 档；渲染耗时 ≈ 视频时长（91s 成片 73s 渲完）
- 版面分区：标题 y 50~165；主视觉 y 180~1100；底部字幕/文案 y 950~1140

## 七步管线（每集照此走）

```bash
PY="C:/Users/49707/.workbuddy/binaries/python/envs/whiteboard/Scripts/python.exe"   # 引擎 venv
SKILL="D:/story-skill/.workbuddy/skills/whiteboard-explainer/scripts"
cd workspace/<project>

# 0) 系列开头：user-gates G0/G1/G3（风格+音色；用户确认前不要往下跑）
# 1) 读原文 → 写 讲稿.md（按 G1 风格；覆盖度自检，见 teaching-script.md）
#    → G2：停，等用户确认讲稿
# 2) 写 make_boards.py（import board_widgets，画完直接产出 plan.build.json）
$PY make_boards.py

# 3) TTS + 精确 cue（voice/rate 用 G3 用户选择；自动删坏分片）
$PY $SKILL/build_narration_fast.py plan.build.json

# 4) 归属质检（必须 0 未归属）
$PY $SKILL/check_assignment.py plan.json

# 5) 冒烟一拍 + 抽帧 → G4：停，等用户说可以全量
$PY $SKILL/render_explainer.py plan.json --out out/<name>.mp4 --only s01
ffmpeg -i out/<name>_parts/s01.mp4 -vf "select=eq(n\,20)" -vframes 1 check/f20.png
$PY $SKILL/render_explainer.py plan.json --out out/<name>.mp4

# 6) 终检
$PY $SKILL/verify_media.py --file out/<name>.mp4 --expect <时长>
```

## make_boards.py 标准模式（核心经验）

```python
import sys
sys.path.insert(0, r"D:/story-skill/.workbuddy/skills/whiteboard-explainer/scripts")
import board_widgets as BW

BW.set_canvas(720, 1280); BW.set_out_dir("boards")
# ...逐拍画：BW.title / person / pyramid / price_tag / arrow_r ...
BW.save(img, "s01", [
    ("title",  (y0, x0, y1, x1), "这拍第一句旁白。"),
    ("visual", [(box1), (box2)], "第二句（多 box 同时画）。"),
    ("deco",   (y0, x0, y1, x1), ""),      # 无旁白=纯图形，并入空间重叠的窗口
])
BW.write_plan("plan.build.json", idea="……")   # 讲稿文本就写在 save() 第三个参数里
```

**box 纪律（EP1 踩坑实录，出问题先查这里）**：

1. box 紧贴内容；一个 region 拆多块空间时**必须用多 box**，不许给一个大 box 罩住别的
   region 的组件（组件 bbox 完整落进两个 box 会被判 spanning，打乱绘制顺序——EP1 的
   「怎么选？」大 box 罩住人物就是这么暴露的）。
2. 相邻 region 的组件间留 ≥18px 白缝；脚踩线的元素统一 `foot = line_y - 10`；
   文字必须落在纯白区域（压色块的字会和色块连成一体）。
3. 同一 region 内元素允许相连（同窗口一起画，无害）；不同 region 相连=cue 失效。
   EP1 实例：s07 绿勾压到招牌 → 勾并进街道组件，勾白缝上移 55px 后才正确后画。
4. 填充色灰度 <240（board_widgets 的色板已保证）；避免 #FFE9 系浅色（会被当白底吞掉）。
5. 一个 region 的绘制量 vs 旁白窗口：中文 ~5.5 字/秒（+22%），一个 3~4s 的窗口放
   1 个主体图形 + 1 行文字是安全密度；超了引擎自动放宽 15%×N，不用手动救。
6. **图标下方/旁边的小标签（人物名、注释）是最常见的漏归属来源**：box 默认只算到
   图形底部，标签 y 超出 box 下边界 → UNASSIGNED。加标签时同步把 box 下边界扩到
   标签底部+15px。资金流/流程箭头的箭杆也要确认在 box 内（箭头常画在 box 外）。
7. **box 约定从 EP15 起改为 (x0, y0, x1, y1) 左上右下**：早期集数用 y 优先序时多次转写出错
   （409 个组件漏归属）。`nb()` 带断言（x1>x0, y1>y0），写反画板阶段即抛异常。
   老脚本（ep01~ep15）不受影响，已渲染完成；新脚本一律 x 优先。
8. **改了 box 必须先删 plan.json 再重跑 build_narration_fast**：plan.json 是从
   plan.build.json 派生的，直接重跑质检读到的还是旧 box（EP11/EP15 各踩一次）。
   固定顺序：`rm plan.json` → build_narration_fast → check_assignment。

## 概念类内容的讲稿骨架（直接套）

发刊词/概念文通用六段式，问题驱动：

1. **Hook**：标题+人物+大问号（"XX 此话怎讲？"）
2. **故事/案例引入**：原文第一个案例画成道具（画架/月饼/飞机…）
3. **概念图形化**：核心对比画成左右结构或阶梯（金字塔 vs 梯形台 / 盾牌 vs ∞）
4. **3 个运用场景**：原文"运用：场景"每场景一拍，道具化（购物车/定金条/婚礼拱门…）
5. **小结/反转**：原文"小结"两条逐条上屏，最后一条给"为什么这样设计"的启发点
6. **互动收尾**：举手人+气泡提问+关注按钮（复用 EP1 s14 版式）

覆盖度自检、单拍 ≤50 字、例子密度等原则见 `teaching-script.md`，不赘述。

## 系列化纪律

- 项目目录 `workspace/fmbs-epNN/`，集号 = 1-based 文章序号（000.md=第1集，002.md=第3集）；
  成片 `out/fmbs-epNN.mp4`。批次任务（如"先做奇数集"）在项目 README 记录映射，防错位。
- **skip 已存在**：分拍 mp4、TTS 分片、成片已存在即跳过；改 boards/讲稿后需删对应分片重渲。
- TTS 失败（NoAudioReceived 三连）：`find audio/narration/parts -name "*.mp3" -size -2k -delete`
  后重跑 build_narration_fast.py，会从缺的分片续跑。
- 每集验收底线：check_assignment 0 未归属 + verify_media PASS + 每集至少抽 2 帧
  （~30% 处与 ~75% 处）目检 cue 顺序。全部通过才进入下一集。

## board_widgets.py 组件清单

人物：`person` `person_cheer`(举手) `person_think`(托腮)；结构：`pyramid` `trapezoid`
`stairs` `office_building` `shop_front`；道具：`price_tag` `coin` `money_stack` `gift_box`
`music_note` `palette` `easel` `gavel` `scales` `open_book` `spotlight` `infinity` `shield`
`mooncake` `work_badge` `laptop` `phone` `cart` `brain_scale`(心形) `burst`(星芒)；符号：
`crown` `qmark` `arrow_r` `bang` `star` `check` `cross` `handshake` `speech`(气泡)
`num_badge` `flag`。画布与产物：`set_canvas` `set_out_dir` `canvas` `text` `title`
`save` `write_plan`。不够用时在本文件追加（画完跑一拍冒烟确认可分窗）。
