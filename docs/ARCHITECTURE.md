# 架构说明：一个本地优先的雅思口语工作台

> 依据当前工作区（2026-10-31）的实际代码整理。先讲运行时、页面和数据，再拆每个子系统，
> 最后给出状态边界、可靠性和扩展点。这里不逐行解释代码，只解释“为什么这样分层”。

## 1. 定位与技术选择

| 维度 | 选择 | 后果 |
| --- | --- | --- |
| 形态 | 本地单机 Streamlit App | 单用户、单进程、无登录、无服务端数据库 |
| 界面 | Streamlit 多页面 + 自定义工作台卡片 | 页面是脚本，状态在 `st.session_state`，刷新即重跑 |
| 数据 | `data/` 下 15 个 JSON + 内置词库 | 可读、可手工修、可用 git 备份；没有联表和事务 |
| 模型 | DeepSeek API / 本地 Ollama，运行时可切换 | 所有智能功能共用一个 `call_llm_json` 出口 |
| 语音 | faster-whisper（可回退 openai-whisper）+ edge-tts | 识别本地、朗读联网；音频按天清理 |
| 网络 | 只监听 `127.0.0.1` | 聊天记录、咨询笔记不会暴露到局域网 |
| 备份 | 原子写 + 按天快照 + 可选私有 git 仓库 | 防误写/损坏，不防硬盘故障 |

核心取向：**数据文件是唯一事实来源，页面只读写它；模型只产出结构化 JSON，
合并、去重、排期、上限全部在本地 Python 里完成。** 这样模型坏了、网络断了，
最多是某次回复失败，不会把学习记录写成半截。

## 2. 运行时全景

```text
┌────────────────────── Streamlit 进程（127.0.0.1:8501）──────────────────────┐
│ app.py：页面注册 + 全局 CSS + 侧边栏（返回 / 音量 / 随手查）                  │
│         + 背景音控制器 + 模型选择                                            │
│                                                                              │
│  工作台 course/dashboard.py：今日打卡 + 练习 / 工具 / 娱乐三块卡片            │
│                                                                              │
│  ┌─ 练习 ───────────────┐ ┌─ 工具 ───────────────┐ ┌─ 娱乐 ──────────────┐  │
│  │ 严肃话题  chats.py    │ │ 雅思老师  Tutor.py    │ │ 日常闲聊 ChatFriend  │  │
│  │ 自由聊天  FreeTalk.py │ │ 笔记本    Notebook.py │ │ 猫娘小屋 CatGirl     │  │
│  │ 讲个故事  Part2.py    │ │ 查资料    Research.py │ │ 心理咨询 Psychologist│  │
│  │ 背单词    Words.py    │ │                      │ │ 学业导师 Mentor      │  │
│  └───────────────────────┘ └──────────────────────┘ └──────────────────────┘  │
│                              隐藏页：老师帮帮我 Help.py                       │
│                                                                              │
│                    utils/ 领域层（38 个模块）                                 │
│  对话：Chat / FreeTalk / Part2 / Tutor / TutorLead / PlanJudge / Entertainment │
│  学习：WordAtlas / SRS / Notebook / Expressions / LongNotes / PrepBook /       │
│        TutorPlan / TutorProgress / NotebookSync / Part2Card / ExamState /     │
│        IeltsRubric                                                            │
│  记忆：Memory / TeacherMemory / TrainingMemory / HelpMemory / Notes /         │
│        ChatHistory / TutorErrors                                              │
│  基建：storage / llm / config / asr / tts / Ambient / conversation /           │
│        QuickLookup / HelpCoach / HelpSession                                   │
│                                                                              │
│     data/*.json（15 个） · assets/word-atlas.json · audio_records/*.mp3        │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼
        DeepSeek API 或 Ollama ｜ faster-whisper ｜ edge-tts（朗读）
```

## 3. 启动、导航与页面外壳

`app.py` 的执行顺序就是全站生命周期：

1. `st.set_page_config`（宽屏）+ 注入全局 CSS（主按钮紫罗兰色、侧边栏间距、随手查按钮尺寸）。
2. 读 `data/ambient.json`，通过父页面注入背景音控制器；之后切页面只更新 `window.__ieltsAmbient`，
   AudioContext 不会被 iframe 重建打断。
3. 初始化模型选择：`session_state.llm_choice` ← `data/model_choice.json` ← `.env`。
4. 构建 `PAGE_TABLE`：每项是 `(文件, 标题, 图标, session_state 键, 是否默认页)`。
   同一张表既生成 `st.Page`，也把页面对象存进 `session_state`，供工作台
   `st.switch_page(st.session_state["page_words"])` 使用。
5. `st.navigation(navigation, position="hidden")`：页面注册，但侧边栏不列入口。
   用户从工作台卡片进入子页，从侧边栏顶部的「← 工作台」返回。
6. 侧边栏三个固定槽位：返回工作台（主页隐藏但保留高度）/ 背景音音量 / 随手查。
7. `pg.run()` 执行当前页面脚本。

`PAGE_TABLE` 的内部注册分组和工作台卡片分组**不完全一致**，这是历史遗留：

| 内部注册分组 | 页面 |
| --- | --- |
| 练习 | 严肃话题、自由聊天、讲个故事、背单词 |
| 工具 | 雅思老师、笔记本、查资料 |
| 娱乐 | 日常闲聊、猫娘小屋、心理咨询、学业导师 |
| 隐藏 | 老师帮帮我 |

工作台实际展示的是：

| 工作台分组 | 页面 |
| --- | --- |
| 练习 | 严肃话题、讲个故事、自由聊天、雅思老师 |
| 工具 | 背单词、笔记本、查资料 |
| 娱乐 | AI友人、摸摸猫娘、心理咨询、学业导师 |

新增页面时以工作台文案为准；`PAGE_TABLE` 只负责注册和页面对象。每个页面自己
`st.set_page_config`，并可以往同一个 `st.sidebar` 叠内容（背景音、模型、随手记、记忆面板）。

> 运维注意：Streamlit 热重载只重新执行页面脚本，不会重新 import `utils/`。
> 改了 `utils/` 必须重启进程，否则可能报 `ImportError: cannot import name ...`。

## 4. 目录与模块

| 路径 | 职责 |
| --- | --- |
| `app.py` | 入口：页面注册、全局样式、侧边栏、模型选择、背景音 |
| `course/dashboard.py` | 工作台：今日打卡聚合 + 三块入口 + 模型/背景音切换 |
| `chats/` | 12 个页面脚本；加工作台共 13 页 |
| `utils/` | 领域逻辑与数据层，38 个模块 |
| `data/` | 个人数据 JSON + `backups/` 快照（gitignore） |
| `assets/word-atlas.json` | 7,298 条内置词库（CC BY 4.0） |
| `static/ambient*/` | 内置 / 自定义背景音，经 `/app/static/` 提供 |
| `models/faster-whisper-base/` | 本地 ASR 模型（可选，gitignore） |
| `audio_records/` | TTS 与单词发音 mp3，保留今天和昨天 |
| `config/.env[.local]` | 模型与语音配置；`.local` 覆盖 `.env` |
| `tests/` | 20 个文件、322 个 `unittest` 用例；页面用 `AppTest` 真渲染 |
| `tools/` | `launch.ps1` / `stop-app.ps1` / `make-shortcut.ps1` / `sync-data.ps1` |
| `docs/` | 架构说明、开发记录、用户测试手册、截图 |

`utils/` 按职责分四组：

| 组 | 模块 |
| --- | --- |
| 对话与页面外壳 | `Chat`、`FreeTalk`、`Part2`、`Tutor`、`TutorLead`、`PlanJudge`、`Entertainment`、`ChatPage`、`HelpCoach` |
| 学习与课程 | `WordAtlas`、`SRS`、`Notebook`、`Expressions`、`LongNotes`、`PrepBook`、`TutorPlan`、`TutorProgress`、`NotebookSync`、`Part2Card`、`ExamState`、`IeltsRubric`、`LearnerProfile` |
| 记忆与记录 | `Memory`、`TeacherMemory`、`TrainingMemory`、`HelpMemory`、`Notes`、`ChatHistory`、`TutorErrors`、`HelpSession` |
| 基础设施 | `storage`、`llm`、`config`、`asr`、`tts`、`Ambient`、`conversation`、`QuickLookup` |

## 5. 页面子系统

### 5.1 工作台（`course/dashboard.py`）

工作台不保存自己的数据，只聚合五个来源：

| 打卡项 | 数据来源 | 口径 |
| --- | --- | --- |
| 背单词·新词 | `WordAtlas.daily_limit()` − 今日已学新词 | 自动计划下每天随考试日期重算 |
| 背单词·复习 | 单词到期 + 笔记本词条到期 | 两者相加 |
| 表达复习 | `Expressions` 到期 | 独立一套间隔，不与单词混用 |
| 课程计划 | `TutorPlan` 未完成点 + `TutorProgress` 今日完成 | 计划全部完成且今天打勾过才算“今日完成” |
| 全部完成 | 上面三类归零 | 才显示“明天见”的祝贺 |

按钮会预置目标页的 `session_state`（例如 `nb_mode="单词 / 词组"`、`nb_word_view="复习"`）
再 `switch_page`，实现“点打卡直接落到对应视图”。

### 5.2 严肃话题（`chats/chats.py` + `utils/Chat.py` + `utils/ExamState.py`）

- 页面标题是「和考官对话」，工作台按钮叫「严肃话题」。
- **状态机**在 `ExamState`：Part 1 / Part 3、当前题号、开场步骤、当前题目清单、最近题目。
- **开场**：考官自报家门 → 问全名 → 问怎么称呼 → 衔接语 + 第一题。开场是独立段落，
  不是 Part 1；即使用户直接从 Part 3 开始，也要先走一遍。
- **题量**：Part 1 一轮 8 题（两个日常话题 × 4），Part 3 一轮 6 题（一个抽象话题）；
  答满后开新一轮。
- **每轮两次并行调用**：
  - `ask_examiner_agent`：回应上一句 + 追问下一题，整条回复控制在 45 词内；
  - `ask_feedback_agent`：一次返回 `correction`（1–3 个真实语法点）、`suggestion`（Band 7 改写）、
    `model_answer`（Band 8–9 参考）。
- 页面下方三栏常驻「语法纠错 / 表达润色 / 高分参考」；最新一条自动朗读（英音 `en-GB-RyanNeural`）。
- 编辑用户消息会按快照把考试状态回退到该消息之后，再重发。
- 录音先转文字，确认后才发送。
- 侧栏有「老师帮帮我」入口；帮助会话不推进考试。

### 5.3 自由聊天（`chats/FreeTalk.py` + `utils/FreeTalk.py`）

- 人设存在 `chat_history.meta.persona` 里，默认是“爱运动音乐的美式大学生”；
  边输入边保存，点「应用人设并重启对话」才会清空当前对话并重新开场。
- 每轮两次并行调用：角色回复 + 反馈（语法 / 润色 / 地道表达）。
- 最新一条自动播放（`en-US-AriaNeural`）；旧消息点播放器重听。
- 支持录音、编辑重发；输入区是多行文本框 + 「提交并获取反馈」，不是回车即发。

### 5.4 讲个故事（Part 2，`chats/Part2.py` + `utils/Part2.py` + `utils/Part2Card.py`）

- **题卡**：LLM 生成 → 本地校验（题面完整、四个提示点合法、不与最近 6 题重复）
  → 不合格重试一次（降温）→ 仍不合格用内置标准题库兜底。
- **持久化**：题卡和答案草稿都落 `data/part2_card.json`；刷新、重开软件后仍是同一张卡、
  同一份答案。只有主动「换一道题」才清空。
- **评估**：并行两路：
  - `ask_feedback_agent` 一次返回 `correction` + `revised_answer`（Band 7 改写）；
  - `ask_model_agent` 生成 Band 8.5 参考范文。
  - 任一路缺失时再补调 `ask_grammar_agent` / `ask_upgrade_agent`；
    改写不足 140 词会走 `_expand_revision` 扩写。
- 反馈经过两层清洗：去掉原文里不存在的“原句”、把习惯性动作误改成过去时的伪纠错；
  `_clean_answer` 还会剥掉模板 token 和中文。
- 页面显示三块：「语法与时态纠错」「修改后的答案 (Band 7+)」「参考范文 (Band 8+)」。
- 答案草稿通过普通键 `part2_answer` 和 `Part2Card` 供「老师帮帮我」读取，老师不用学生再贴一遍。
- 评估结果只在内存；题卡和草稿落盘。

### 5.5 雅思老师（`chats/Tutor.py` + `utils/Tutor*`、`PrepBook`、`PlanJudge`、`TeacherMemory`）

这是全站最复杂的子系统，也是唯一“有课程计划”的练习。

**计划从哪来**

```text
备课本 prep_book.json（唯一候选池）
  ├─ 弱词：LearnerProfile.weak_words（来自 word_progress 的遗忘/到期/ease）
  ├─ 笔记本：LearnerProfile.notebook_lines（只取单词/词组）
  └─ 用户手动点：user_request
       │ sync_candidates（按 source_key 去重，seen 只进一次）
       ▼
TutorPlan.create_plan()
  ├─ 自动最多 3 个点；最近三个计划配额：最新 0、上一个 1、上上个 2
  ├─ 第一个取“最早加入”，其余按“最新加入”
  ├─ LLM 只写 goal / warmup / 每点 task+criterion / wrapup
  └─ lesson_id（8 位 hex）+ points[] + history[]
```

- 未完成的计划不会被悄悄覆盖；计划完成后可以手动「更新计划」，或等当天第一次打开时自动更新。
- 首次使用（计划为空）不会自动生成：先在「我想练」里加点，或从备课本生成。
- 计划最多 10 个点；`history` 保留最近 10 课。
- 同一个点第二次完成会从备课本退休（`seen` 保留，不再自动加回）。

**一轮对话的分流**

```text
用户输入
 ├─ 训练中且是“好/yes”          → 只提醒直接作答
 ├─ 训练中且要换点             → _begin_training(新点)
 ├─ 明确的“我想练 X”           → 取计划里的点 / 加入「我想练」待确认
 ├─ 训练中且是提问/求助         → 暂停训练，回答问题
 ├─ 训练中且是作答             → _coach_practice（教练回合）
 ├─ “记住…”                   → Memory.remember("tutor")（写进「关于你」）
 ├─ 纯英文单词/短语（≤5 词）    → explain_vocabulary（词典卡 + 发音）
 └─ 其它                       → ask_tutor_turn（普通回合）
```

**普通回合的调用预算**

| 步骤 | 模块 | 作用 |
| --- | --- | --- |
| 1 | `Tutor.ask_tutor_turn` | 后台老师：回复草稿 + `new_issues`；`no_drill=True` 关闭自动转训练 |
| 2 | `TutorErrors.add_errors` | 本地合并错误，等用户决定是否进备课本 |
| 3 | `TutorLead.compose` | 表达层：把草稿说成人话，保留所有「原句/改句」 |
| 4 | `PlanJudge.judge_message` | 独立裁判：本条消息在练哪个点、哪些点已完成 |
| 5 | `TutorPlan.mark_point` | 打勾 → `TutorProgress.record` + 更新 history + 二次完成则退休 |
| 6 | `Memory.update_memory("tutor")` | 后台：记住学生这个人 |

> `ask_tutor_turn` 的 `practice` 交接被 `no_drill=True` 关闭；训练入口是前面的意图层
> （「我想练」「开始练」或训练中的换点指令）。这是有意设计，不是死代码。

**训练回合**

1. `_begin_training` → `ask_practice_question` 出题，同时生成内部 `model_answer`；
2. `TutorLead.compose` 说成自然口语，`_start_coaching_direct` 写入训练状态；
3. 学生作答 → `coach_practice_answer` 返回 `feedback/focus/status/checklist/usage/new_issues`；
4. `TutorLead.compose` 改写反馈；
5. `PlanJudge` 判断是否打勾；
6. `TrainingMemory.update_async` 写训练期临时记忆；
7. 首轮/末轮触发 `TeacherMemory.update_from_lesson` 更新学习档案。

**“老师”其实是两层**

- 后台老师（`Tutor.py`）：出题、判分、维护 checklist，输出内部 brief；
- 表达层（`TutorLead.py`）：学生唯一听到的声音，会判断此刻该不该练（`keep_practice`），
  失败时原样返回 brief。
- 纠错引号有校验（`_quotes_preserved`），防止表达层把 `「I go there」→「I went there」` 改坏。

**裁判是第三个视角**

`PlanJudge` 不看陪练内部状态，只看“当前可见回复 + 上一条可见回复 + 未完成点”：

- 老师开始问下一个点 → 上一个点完成；
- 综合练习明确用到多个点 → 这些点完成；
- 还在改同一个点 → 不打勾；
- 返回值必须落在 pending 的 `source_key` 白名单里，模型编造的点会被丢弃；
- 另有 `judge_conversation` 供「强制检测是否完成」补齐漏判，并用正则兜底整段通过。

**老师相关的四份记忆**

| 文件 | 回答的问题 | 写入者 |
| --- | --- | --- |
| `teacher_memory.json` | 学生的水平、习惯、强弱项、有效教法、课堂成果、考试过程 | `TeacherMemory.update_from_lesson` / `remember_outcome` / `remember_exam_session` |
| `memories.json["tutor"]` | 学生是什么人（名字、身份、偏好、在意的事） | `Memory.update_memory`（训练中不写） |
| `memories.json["tutor_training"]` | 这一节课内反复出现的临时上下文 | `TrainingMemory.update_async` |
| `tutor_errors.json` | 还没决定要不要练的具体错误 | `TutorErrors.add_errors` |

再加 `chat_history.json["tutor"]`（消息与训练元数据）和 `prep_book.json`（候选池），
一个“老师”实际由 6 份数据共同塑形。

### 5.6 老师帮帮我（`chats/Help.py` + `utils/Help*`）

- 入口只有两个：严肃话题侧栏、讲个故事侧栏；工作台没有入口。
- `HelpSession` 把考官对话和 Part 2 分成两份互不干扰的临时聊天（`help_exam` / `help_part2`），
  并用 `help_active` 元数据记住当前来源。
- 老师能看到当前考试状态、当前题目，或者 Part 2 的题卡和学生答案；
  Part 2 答案从 `part2_answer` / `Part2Card` 读取。
- **固定参考回答**：同一道题只生成一次 `preset_answer`，后续提示都围绕它，避免标准变来变去。
- `HelpCoach.advise` 只给一条引导式提示（`one_hint` 截到约 260 字），不替学生答完整题。
- `HelpMemory` 是这一场求助的临时记忆；长期记忆（学习档案 / 关于你）只读不写。
- 点「结束帮助」时 `HelpMemory.finish` 把摘要写进 `teacher_memory.exam_notes` 的「考试过程」，
  然后清空临时会话。

### 5.7 背单词（`chats/Words.py` + `utils/WordAtlas.py` + `utils/SRS.py`）

- 词库 `assets/word-atlas.json`：7,298 条，字段含 CEFR、释义、例句、搭配、词族、近反义词等。
- 今日队列 `build_queue()` = 到期复习（按 due 升序）+ 新词额度，上限 60：
  - 新词额度 = `daily_limit() - 今日已学新词`；
  - 手动模式取 `settings.new_per_day`，自动模式取考试计划的每日新词（均限 1–50）；
  - 新词按 CEFR 起始级与话题过滤后，按词库顺序取未学过的。
- 三阶段主动回忆由 `reps` 决定：
  - `reps == 0`：看词选义；
  - `reps == 1`：看义选词；
  - `reps >= 2`：例句填空拼写（答案忽略空格/连字符/撇号）。
- 评分 `again / hard / good / easy` 走共享 SRS：间隔 1 → 3 → ×ease，上限 180 天，
  ease 1.3–3.0；`again` 当天重来并 `lapses+1`。
- 考试计划 `exam_plan()`：目标分按 0.5 分一档映射 CEFR 范围（如 7.5 → B2–C1）；
  考试日期 → 剩余天数，最后 7 天只复习；每日新词 = `ceil(剩余未学 / max(1, 天数 - 7))`。
- 「巩固已学」按 `lapses×2 + (3-reps) + 到期` 评分取最弱 10 个。
- 单词发音缓存为 `audio_records/wa_<id>.mp3`，0 字节视为无效重新合成。

### 5.8 笔记本（`chats/Notebook.py` + `utils/Notebook.py`、`Expressions.py`、`LongNotes.py`、`NotebookSync.py`）

「笔记本」页有三个 tab：

| 库 | 文件 | 主键 | 用途 |
| --- | --- | --- | --- |
| 单词 / 词组 | `notebook.json` | 12 hex | 词条 + 逐义项释义/例句 + 标签 + 语义分组 + SRS |
| 表达 | `expressions.json` | 12 hex | 中文意图 → 地道英文 |
| 仓库（便签） | `long_notes.json` | 12 hex | 长文本、语法笔记、范文，按日期归档 |

- **词条补全**：`add_entry` 默认 `enrich=True`，一次 LLM 调用补全逐义项翻译、
  每义项一条雅思例句、标签（18 个固定标签）和语义分组（17 个标准组）。
  侧栏「随手查」保存走 `enrich=False`，不调模型。
- **复习**：词条用共享 SRS；表达用自己的阶梯 1→3→7 天，之后 ×2、上限 120 天，
  `interval >= 21` 天记为已掌握。
- **检索**：搜索 term/释义/例句/标签/分组；`order_by_relevance` 用汉字单双字、标签、
  分组、英文词做 Jaccard 相似度，同组再加 0.25。
- **导出**：单词库导 `notebook.json`、表达库导 `expressions.json`、仓库导 `warehouse_notes.json`。
- **同步**：`NotebookSync` 在删/改词条后更新备课本和当前计划；正在训练的点也会跟着改名或结束，
  避免继续练旧词。

### 5.9 查资料（`chats/Research.py`）

最普通的对话页：一次 LLM 调用，按用户语言回答；不做联网检索，没有记忆、语音或计划。
聊天记录仍写 `chat_history`（key `research`），侧栏有随手记和重新开始确认框。

### 5.10 娱乐（`chats/ChatFriend.py`、`CatGirl.py`、`Psychologist.py`、`Mentor.py` + `utils/ChatPage.py`）

- `ChatPageSpec` 收拢了开场白、播放器、记忆侧栏、会话笔记和重新开始。
- 四个角色页只保留人设、文案、音色和 `memory_key`。
- 这四个页面**不提供语音输入，也不做消息编辑**；说错了只能重新发一条。
- 每轮 **通常一次** LLM 调用：角色永远用英文回；用户说中文时同一次调用再返回 `reply_zh`，
  页面显示中文、TTS 读英文。回复与上一条过于相似时会重写一次。
- 回复后最多两个后台线程：`Memory.update_memory`（长期记忆）和
  `Notes.update_session_note`（仅心理咨询 / 学业导师，写带日期的会话笔记）。
- 学业导师侧栏「选择专业」存在 `chat_history.meta.major`，默认「电子信息工程」；
  换专业只换人设里的领域，导师的语气、结构、追问要求不变。
- 四个角色：

| 页面 | session 前缀 | 记忆 key | 音色 | 会话笔记 |
| --- | --- | --- | --- | --- |
| 日常闲聊 | `friend` | `companion` | `en-GB-RyanNeural` | 无 |
| 猫娘小屋 | `cat` | `catgirl` | `en-GB-MaisieNeural` | 无 |
| 心理咨询 | `psy` | `psychologist` | `en-US-AriaNeural` | `psychologist` |
| 学业导师 | `mentor` | `mentor` | `en-GB-ThomasNeural` | `mentor` |

### 5.11 全站能力

| 能力 | 实现 |
| --- | --- |
| 随手查 | 侧边栏表单输入 → `QuickLookup.lookup`；英文→中文义项+例句，中文→3–5 个英文说法；结果只在内存 |
| 随手记 / 加入笔记本 | 练习页侧栏 `render_jotting_sidebar`：单词/词组、表达、仓库三选一；仓库只读列表 |
| 聊天记录 | 每页独立 key，写 `chat_history.json`，最多 300 条，刷新/重开浏览器不丢 |
| 模型切换 | 工作台下拉框 → `session_state.llm_choice` + `data/model_choice.json`，全站即时生效 |
| 背景音 | 6 段内置 CC0 + `static/ambient-local/` 自定义；父页面 AudioContext 循环播放，切页不断 |
| 自动备份 | 写入前按天快照，保留 30 天；坏文件先隔离再覆盖 |
| 本地绑定 | `.streamlit/config.toml` 固定 `address=127.0.0.1` |

## 6. 数据模型

15 个 JSON，按用途分四组。

### 6.1 运行配置

```jsonc
// model_choice.json
{"version": 1, "provider": "deepseek|ollama", "model": "deepseek-flash"}

// ambient.json
{"version": 1, "track": "rain|waves|...", "volume": 35}
```

### 6.2 对话与记忆

```jsonc
// chat_history.json —— 每页一个 session key
{"version": 1, "sessions": {
  "tutor": {
    "messages": [{"role": "user|assistant", "content": "...", "audio": "...",
                  "correction": "", "suggestion": "", "model_answer": "",
                  "items": [/* 词典卡，可选 */]}],
    "meta": {
      "persona": "自由聊天人设",
      "major": "专业方向（学业导师）",
      "session_id": "12hex", "session_date": "2026-10-30",
      "training": {"point": [], "question": "", "model": "", "stage": "answer|coaching",
                    "focus": "", "checklist": [], "turns": 0, "lesson": "8hex"},
      "exam_state": {"selected_part": "part1", "index": 3, "questions": []},
      "plan_last_points": ["source_key"], "plan_lesson": "lesson_id",
      "help_context": {"source": "exam|part2", "started_at": "..."},
      "preset_answer": {"question": "...", "answer": "...", "updated_at": "..."}
    },
    "updated_at": "2026-10-30 01:00:00"
  }
}}
```

- `help_exam` / `help_part2` 存放两场求助的临时消息；`help_active` 只存当前来源。
- `research` 是「查资料」的 key；`exam`、`free_talk`、`tutor`、`friend`、`catgirl`、
  `psychologist`、`mentor` 各自独立。

```jsonc
// memories.json —— 娱乐角色、老师、训练期、求助期的长期/临时记忆
{"version": 2, "personas": {
  "catgirl": {"summary": "≤300 字画像",
              "facts": [{"text": "≤60 字", "count": 3,
                         "first": "...", "last": "...", "permanent": true}],
              "updated_at": "..."}
}}
```

记忆 key：`companion`、`catgirl`、`psychologist`、`mentor`、`tutor`、
`tutor_training`、`help_exam`、`help_part2`。后三个是隐藏 persona，不出现在侧栏。

```jsonc
// session_notes.json —— 按会话 id 的诊疗/指导笔记
{"version": 1, "notes": {"psychologist": {
  "3173e35857b5": {"date": "2026-10-29", "summary": "≤200 字",
                    "details": ["≤60 字"], "next": ["≤60 字"],
                    "created_at": "...", "updated_at": "..."}
}}}

// tutor_errors.json —— 待整理知识点
{"version": 1, "items": [{"text": "≤120 字", "count": 2, "first": "...", "last": "..."}]}
```

### 6.3 学习数据

```jsonc
// word_progress.json
{"version": 1,
 "words": {"rally": {"due": "2026-11-02", "interval": 3, "reps": 2,
                     "ease": 2.5, "lapses": 0, "last": "2026-10-30",
                     "added": "2026-10-28 10:00:00"}},
 "daily": {"2026-10-30": {"new": 10, "review": 22}},
 "settings": {"new_per_day": 10, "start_cefr": "A1", "topics": [],
              "exam_date": "2027-06-30", "target_band": 7.5,
              "auto_plan": true}}

// notebook.json
{"version": 1, "entries": [{
  "id": "2f47a5af55d0", "term": "all set", "meaning": "phr. 准备就绪的",
  "senses": [{"pos": "phr.", "meaning": "准备就绪的", "example": "..."}],
  "example": "...", "note": "", "tags": ["口语", "生活"], "group": "状态描述",
  "source": "自由聊天", "created_at": "...", "updated_at": "...",
  "review": {"due": "2026-11-01", "interval": 3, "reps": 2,
             "ease": 2.5, "lapses": 0, "last": "2026-10-29"}}]}

// expressions.json
{"version": 1, "entries": [{
  "id": "6f16c2271686", "intent": "我能听清", "natural": "I can hear you very clearly",
  "scene": "考官问候",
  "source": "严肃话题", "created_at": "...", "updated_at": "...",
  "review": {"due": "2026-11-01", "interval": 3, "streak": 2,
             "lapses": 0, "last": "2026-10-29"}}]}

// long_notes.json
{"version": 1, "entries": [{
  "id": "c9084c8ee8ac", "date": "2026-10-29", "title": "坚持不悔，欣赏的老师",
  "content": "...", "created_at": "...", "updated_at": "..."}]}

// part2_card.json
{"version": 1, "cue_card": "Describe ...", "answer": "学生草稿",
 "updated_at": "...", "answer_updated_at": "..."}
```

### 6.4 课程链路

```jsonc
// prep_book.json —— 候选池；seen 保证同一来源只自动进一次
{"version": 1,
 "items": [{"source_key": "word:rally", "label": "rally（n. 公众集会）",
            "kind": "word|phrase", "source": "weak_word|notebook|user_request",
            "added_at": "2026-10-30 00:42:07.201792"}],
 "seen": ["word:rally", "notebook:..."]}

// tutor_plan.json —— 当前课 + 最近 10 次课的索引
{"version": 2, "lesson_id": "a1b3fe45",
 "goal": "学会用一个中文短句表达对某件事的感受。",
 "warmup": "...", "wrapup": "...",
 "points": [{"source_key": "word:irritation", "label": "irritation（n. 恼怒）",
             "kind": "word", "source": "weak_word",
             "task": "...", "criterion": "...",
             "status": "pending|mastered", "mastered_at": "",
             "added_by": "auto|user"}],
 "status": "empty|active|done",
 "created_at": "...", "updated_at": "...", "last_auto_plan_date": "2026-10-30",
 "history": [{"lesson_id": "0c7a9244", "created_at": "...", "goal": "...",
              "source_keys": ["word:tug"], "status": "done|active"}]}

// tutor_progress.json —— 独立于计划的每日完成流水
{"version": 1, "days": {"2026-10-29": {"points": [
  {"lesson_id": "0e7a9244", "source_key": "word:tug",
   "label": "tug（用力拉）", "at": "2026-10-29 12:47:28"}]}}}

// teacher_memory.json —— 老师对学生的长期画像
{"version": 1,
 "level": {"band": "5.5-6.0", "note": "...", "updated": "..."},
 "style": [{"text": "句子偏长", "count": 1, "first": "...", "last": "..."}],
 "strengths": [], "weaknesses": [{"text": "which 从句单复数", "count": 2}],
 "methods": [{"text": "对比句比讲规则有效", "count": 1}],
 "outcomes": [{"text": "上节课练成了什么", "date": "2026-10-31", "lesson": "92a6b0ad"}],
 "recent": [{"date": "2026-10-29", "summary": "...", "next": "...", "lesson": "92a6b0ad"}],
 "exam_notes": [{"date": "2026-10-31", "source": "模拟考试求助",
                 "summary": "..."}],
 "updated_at": "..."}
```

`exam_notes` 由「老师帮帮我」结束时写入，最多 12 条；它和 `recent` 不是一回事：
`recent` 是正式课的记录，`exam_notes` 是考场旁求助的记录。

### 6.5 主键与外键

系统没有数据库外键，靠约定键连接记录：

| 连接键 | 形态 | 谁产生 | 谁消费 |
| --- | --- | --- | --- |
| 词条 id | 小写 headword（`rally`） | `word-atlas.json.id` | `word_progress.words` 的 key、`word_by_id` |
| 笔记本 id | 12 位 hex | `Notebook.add_entry` | 复习、编辑、删除 |
| 表达 id | 12 位 hex | `Expressions.add_expression` | 复习、编辑、删除 |
| 便签 id | 12 位 hex | `LongNotes.add_note` | 编辑、删除、导出 |
| `source_key` | `命名空间:规范化标签` | `PrepBook` / `TutorPlan` | 备课本、计划点、进度流水、裁判 |
| `lesson_id` | 8 位 hex | `TutorPlan.create_plan` | 计划、history、`tutor_progress`、`teacher_memory.outcomes.lesson` |
| 训练 lesson | 8 位 hex | `_start_coaching_direct` / 实时进训练 | `chat_history.meta.training.lesson`、`teacher_memory.recent.lesson` |
| 会话 id | 12 位 hex | `ChatPage` / `Notes` | `session_notes.notes[kind]`、`chat_history.meta.session_id` |
| 聊天 session key | `exam/free_talk/tutor/friend/catgirl/psychologist/mentor/research/help_*` | 页面写死 / `ChatPage.prefix` | `chat_history.sessions` |
| 角色 key | `companion/catgirl/psychologist/mentor/tutor/...` | `ChatPageSpec.memory_key` / 模块常量 | `memories.personas` |

> 训练 lesson 和计划 `lesson_id` 不保证是同一个值；前者标识“这一次训练”，
> 后者标识“这一课的计划”。查 `teacher_memory.recent.lesson` 时不要拿计划 id 去反查。

`source_key` 的命名规则（`PrepBook._source_key_for`）：

| 来源 | 规则 | 例子 |
| --- | --- | --- |
| 弱词 | 英文头词 → `word:<word>` | `word:rally` |
| 笔记本单词 | 同上（同一词跨来源天然合并） | `word:timeless` |
| 笔记本词组 | `notebook:<去括号/标点、casefold>` | `notebook:what have you been up to` |
| 用户指定 | `user_request:<规范化标签>` | `user_request:can't help doing` |
| 计划内临时点 | `user:<规范化标签>` / `plan:<规范化标签>` | `user:过去时态不一致` |
| 旧表达库 | `expression:<规范化标签>` | 只用于识别旧数据，同步时会被清掉 |

规范化：去尾部括号注释、去尾部标点、压缩空白、casefold；单词取第一个英文词。
所以“从弱词进来”和“从笔记本进来”的同一个词只会占一条备课本记录。

### 6.6 数据是怎么串起来的

```text
assets/word-atlas.json
        │ id
        ▼
data/word_progress.json ──stats/weak_words──┐
                                            │
data/notebook.json ────notebook_lines───────┤
                                            ▼
                                  utils/PrepBook.sync_candidates
                                            │ source_key
                                            ▼
                                  data/prep_book.json (items + seen)
                                            │ _select_points（配额）
                                            ▼
                                  data/tutor_plan.json (points/history)
                                     │                    ▲
                    ask_tutor_turn / _coach_practice      │ mark_point
                                     │                    │
                                     ▼                    │
                            visible reply ──> PlanJudge ───┘
                                     │ completed
                                     ▼
                          data/tutor_progress.json (days)
                                     │
                                     └──> course/dashboard.py「今天」

data/chat_history.json ──────────────> 页面恢复 + 训练状态
data/teacher_memory.json ────────────> 备课 / 陪练 / 表达层 prompt
data/memories.json["tutor"] ─────────> 表达层「关于你」
data/tutor_errors.json ──确认后──────> 备课本（加 user_request 点，再删错误）
data/session_notes.json ─────────────> 咨询/导师侧栏
data/long_notes.json ────────────────> 各页「仓库」侧栏
data/part2_card.json ────────────────> Part 2 题卡、草稿、帮助页上下文
```

表达库不进备课本：它只走自己的复习阶梯。能变成课的是**弱词**和**笔记本里的单词/词组**。

### 6.7 首页「今天」的聚合口径

`course/dashboard.py` 不自己存数据，只读：

| 打卡项 | 数据来源 | 计算 |
| --- | --- | --- |
| 背单词·新词 | `daily_limit()` − `daily[today].new` | 剩余额度（自动计划随考试日期变） |
| 背单词·复习 | `word_progress.words[*].due <= today` + `notebook.entries[*].review.due <= today` | 到期总数 |
| 表达复习 | `expressions.entries[*].review.due <= today` | 到期条数 |
| 课程计划 | `tutor_plan.points` + `tutor_progress` | 未完成点数 / 今日完成数 |
| 全部完成 | `word_review_remaining == 0` 且 `new_quota == 0` 且 `exp.due == 0` 且 `tutor_done_today` | 显示祝贺 |

其中 `tutor_done_today` 要求计划本身全部完成，且某个点的 `mastered_at` 是今天；
即使今天重新备过课，`tutor_progress.today_count()` 仍独立累计，不会被清零。

### 6.8 哪些数据会进 prompt

| Prompt | 注入的数据 | 上限 |
| --- | --- | --- |
| 老师普通回合 | `teacher_memory`、`tutor_plan.plan_text`、最近 10 条历史 | 历史每条 700 字 |
| 老师陪练回合 | 题目、目标点、`teacher_memory`、plan、checklist、focus、内部 model answer | 作答 2000 字 |
| 老师表达层 | 整场 transcript、`teacher_memory`、`memories["tutor"]`、plan、brief | transcript 20k 字，brief 2.2k |
| 备课 | `TeacherMemory.memory_text` | — |
| 计划裁判 | 未完成点、当前目标、上一条/当前可见回复（整场版为 120 条 × 500 字） | — |
| 娱乐角色 | `memories[persona]`（永久事实单独成段）+ 最近 10 条 | 事实 14 条 |
| 会话笔记 | 最近 12 条、每条 350 字 + 已有笔记 | — |
| 笔记本补全 | 已有分组（25 个）、已有标签（30 个）+ 标签体系 | — |
| 学习档案 | 已学/到期统计、最该复习 8 词、最近 6 笔记、最近 6 表达 | — |
| 帮助页 | 当前考试/Part 2 上下文、求助原文、固定参考回答、帮助临时记忆 | 提示约 260 字 |

## 7. 关键链路

### 7.1 词汇 → 备课本 → 计划

```text
背单词答题
  └─ WordAtlas.apply_review → word_progress.words[id]（SRS）
       └─ stats()/build_queue() → 首页「背单词」打卡 + 次日到期队列
            └─ LearnerProfile.weak_words()（lapses / ease / 到期）
                 └─ PrepBook.sync_candidates → prep_book.items
                      └─ TutorPlan.create_plan → 老师用这个词出题
                           └─ 学生用错 → TutorErrors → 用户确认 → PrepBook
```

### 7.2 老师普通回合

```text
学生输入
└─ [S1] chats/Tutor.py::_send
   ├─ history 快照，append user，ChatHistory.save("tutor")
   ├─ 分流器（命中即 return）
   └─ 普通回合
      ├─ [S2] ask_tutor_turn(no_drill=True)      LLM#1 → reply + new_issues
      ├─ [S3] TutorErrors.add_errors             → tutor_errors.json
      ├─ [S4] TutorLead.compose                  LLM#2 → 学生看到的 reply
      ├─ append assistant，ChatHistory.save
      ├─ [S5] PlanJudge.judge_message            LLM#3 → completed
      │    └─ TutorPlan.mark_point → TutorProgress.record → prep_book 退休
      └─ [S6] 后台 Memory.update_memory("tutor")  LLM#4 → memories["tutor"]
```

### 7.3 老师训练回合

```text
[A] 进入训练（「我想练」/ 训练中换点 / 裁判实时切换）
└─ _begin_training
   ├─ ask_practice_question([{label, kind}], memory)   LLM#1 → question + model_answer
   ├─ TutorLead.compose                                 LLM#2 → 口语化出题
   └─ _start_coaching_direct → 写 training 状态、保存 chat meta

[B] 学生作答
└─ _coach_practice
   ├─ coach_practice_answer(question, targets, answer, focus, checklist,
   │                         model_answer, memory, plan) LLM#3
   ├─ TutorErrors.add_errors
   ├─ TutorLead.compose                                 LLM#4
   ├─ PlanJudge.judge_message                           LLM#5
   ├─ 后台 TrainingMemory.update_async                  LLM#6
   └─ 首轮/末轮 后台 TeacherMemory.update_from_lesson    LLM#7
```

时序注意：

- 裁判是同步的，决定是否打勾/切下一个点；
- 训练记忆和学习档案是后台的，不阻塞学生看到回复；
- `TrainingMemory` 只写训练期临时上下文，不进入「关于你」；
- 换计划时 `ensure_lesson` 会把上节课的摘要写进 `teacher_memory.outcomes`，再销毁临时记忆；
- `chat_history.meta.training` 是刷新后恢复“训练中”状态的唯一来源。

### 7.4 老师帮帮我

```text
严肃话题 / 讲个故事侧栏 → HelpSession.start(source)
  └─ 读 ExamState + chat_history["exam"]，或 Part2Card + part2_answer
       └─ preset_model_answer（每题一次）      LLM#1
            └─ 学生提问
               ├─ HelpCoach.advise              LLM#2
               ├─ one_hint（只留一条提示）
               ├─ TutorLead.compose("help")     LLM#3
               └─ HelpMemory.update_async       LLM#4（后台）
                    └─ 结束帮助 → TeacherMemory.remember_exam_session
```

### 7.5 Part 2 持久化

```text
进入页面
  └─ Part2Card.get()：session → data/part2_card.json → 都没有才生成
       └─ get_or_create(generate_cue_card)
            └─ 答案草稿 on_change / 语音转写 → Part2Card.save_answer
                 └─ 换一道题 → 清题卡、清草稿、清帮助会话
```

## 8. LLM、语音与背景音

### 8.1 LLM 调用层

`utils/llm.py` 是全站唯一出口：

- `call_llm_json(prompt, temperature, num_predict, fallback, timeout, provider, model)`
  按当前选择分发到 DeepSeek（OpenAI 兼容 `/chat/completions`，`response_format=json_object`，
  `thinking: disabled`）或 Ollama（`format=json`，`num_ctx=4096`）。
- **失败约定**：返回 `{"_fallback": fallback}`（`fallback=None` 时返回 `{}`），
  业务模块据此给兜底文案，页面不会崩。
- 重试：仅 408/409/425/429/5xx，最多 2 次，优先 `Retry-After`，否则 1s/2s，最多 10s；
  400/401/403 不重试。
- JSON 容错：剥离 ```json 围栏 → 取第一个 `{...}` → 解析失败再从截断文本里抢救一个字段。
- 记账：DeepSeek 的 `usage` 写入进程内 `deque(maxlen=100)`，`usage_log()` 可查。
- **线程规则**：后台线程读不到 Streamlit `session_state`，所有后台调用必须显式传
  `provider/model`（`Memory`、`Notes`、`TrainingMemory`、`HelpMemory`、`Tutor` 都遵守）。

每类功能的调用预算：

| 场景 | 调用数 | 说明 |
| --- | ---: | --- |
| 严肃话题 / 自由聊天 每轮 | 2 并行 | 角色回复 + 反馈 |
| Part 2 出题 | 1–2 | 校验失败重试 |
| Part 2 评估 | 2 并行（+0–2 兜底） | 点评+改写 / 范文 |
| 老师普通回合 | 3（+1 后台） | 回合 / 表达 / 裁判 / 记忆 |
| 老师训练回合 | 2–3（+2 后台） | 教练 / 表达 /（裁判）；后台训练记忆 + 学习档案 |
| 老师启动训练 | 2 | 出题 + 表达层（随后仍走裁判） |
| 老师查词 | 2（+≤8 TTS） | 拆条讲解 + 表达层；每条词卡一次朗读 |
| 老师备课 | 1 | 写 goal/task/criterion（失败用模板兜底） |
| 打开老师页 | 0–2 | 需要重开计划时 1 次；新会话开场白 1 次 |
| 老师帮帮我 | 2–3（+1 后台） | 参考回答 / 提示 / 表达层 / 临时记忆 |
| 娱乐每轮 | 1（+2 后台） | 回复（含中文翻译）/ 记忆 / 笔记 |
| 笔记本新增 | 1 | 补全义项与标签 |
| 便签自动标题 | 1 | 仅标题为空时 |
| 随手查 | 1–2 | 英文词复用笔记本算法 + 例句翻译 |
| 查资料 | 1 | 普通回答 |

### 8.2 语音与媒体

**识别链路**：`st.audio_input` → MD5 去重（避免组件收尾重复触发）→ 写系统临时文件 →
`asr.get_model()`（进程内单例，faster-whisper 优先，失败回退 openai-whisper）→
文本放进输入框，**用户确认后才发送**（`vad_filter=True`、`beam_size=5`）。
识别语言固定为英文。

**朗读链路**：`tts.speak` → `edge-tts` 写 `<file>.part` → `os.replace` 成名 →
`existing_audio` 校验存在且非 0 字节 → `st.audio`；页面只自动播放“最新一条”。
`audio_records/` 每个进程每天扫一次，保留今天和昨天。

音色：严肃话题/日常闲聊默认 `en-GB-RyanNeural`；学业导师 `en-GB-ThomasNeural`；
猫娘 `en-GB-MaisieNeural`；心理咨询/自由聊天 `en-US-AriaNeural`。

**背景音**：`Ambient.player_html` 把控制器源码注入父页面 `window`，用
`AudioBufferSourceNode` 循环（`loopStart/loopEnd` 各裁 0.06s 去除解码补白），
切歌淡出 1.2s / 淡入 2s；浏览器自动播放策略拦截时显示「🔊 点击开启背景音」。
优先使用 `static/ambient-local/` 下的自定义音轨，没有才回退到 `static/ambient/` 的 6 段 CC0。

## 9. 状态边界与可靠性

### 9.1 什么在内存，什么在磁盘

| 只在 `session_state` | 落盘 |
| --- | --- |
| 当前页面对象（`page_*`）、`llm_choice` | `model_choice.json` |
| 各页 `messages` / `tutor_messages` | `chat_history.json`（每轮） |
| 编辑模式、输入缓冲、录音去重 id | — |
| `part2_evaluation`、当前答题队列/位置 | —（评估故意不存） |
| 随手查结果 | —（故意不存） |
| 训练中的 focus/checklist/stage | `chat_history.meta.training` |
| 当前题卡与答案草稿 | `part2_card.json` |
| 背景音选择/音量 | `ambient.json` |

因此：**刷新会丢“当前评估、当前队列位置、随手查结果”，但不会丢单词进度、
计划、聊天记录、记忆、笔记、Part 2 题卡和答案草稿。**

### 9.2 `storage.py` 的三条硬保证

1. **原子写**：`.tmp` + `flush` + `fsync` + `os.replace`（Windows 占用重试 3 次）；
2. **按天快照**：每个文件每天第一份旧内容存 `data/backups/<stem>-YYYYMMDD.json`，
   保留 30 天（按“最近 N 份”会被高频写入挤掉，所以按天）；
3. **坏文件隔离**：写入前发现现有内容不是合法 JSON，先复制到 `backups/corrupt/` 再覆盖。

其他防护：

- 内容没变不写、不生成快照；
- 每个数据模块一把模块级 `RLock`，只锁读-改-写，LLM 调用在锁外；
- 角色记忆“只合并、不整份覆盖”，模型少写一条不会丢事实；
- 表达层校验「…」引号必须原样保留，否则退回 brief；
- 计划裁判只接受 pending 白名单里的 `source_key`；
- 各处上限：聊天 300 条 / 单条 2 万字、备课本 200、待整理错误 50、计划 10 点、
  历史 10 课、进度 400 天、每角色记忆 14 条（永久 10）、老师画像 5/5/5/4/6 + recent 4、
  `exam_notes` 12 条、音频保留 2 天。

### 9.3 已知边界

这些是单机单用户假设下的取舍，不是待修的 bug：

- 多浏览器标签同时写同一 JSON 时，最后写入者覆盖（锁只在进程内）；
- 跨文件没有事务：例如“打勾计划点”与“写进度流水”是两次写；
- 备份与数据同盘，不防硬盘故障；`tools/sync-data.ps1` 是异地的唯一手段；
- 训练**只**由「我想练 / 开始练 / 换点」这类意图启动，普通聊天不会自动进入训练；
- Part 2 的评估结果只在内存，刷新就没了；题卡和答案草稿会保留；
- 语音识别固定按英文跑；`edge-tts` 需要联网；
- 老师侧栏的「英语学习档案」面板已隐藏，但后台仍每课更新 `teacher_memory.json`；
- 单词、笔记本词条、表达是三套间隔重复，统计不能混看；
- 所有个人数据是明文 JSON，私有 git 仓库不等于加密；
- AI 的纠错、改写、评分和范文只用于练习参考，不代表官方评分。

## 10. 测试与运维

- **322 个 `unittest` 用例 / 20 个文件**，不联网、不花钱：
  `python -m unittest discover -s tests -v`。
  - `test_core.py`：存储/备份、LLM JSON、题卡清洗、SRS、音频清理；
  - `test_pages.py`：用 `AppTest` 真渲染每个页面并走发送/加点/训练流程；
  - `test_tutor_*` / `test_plan_judge` / `test_prep_book` / `test_teacher_memory`：
    老师链路；
  - `test_help_*` / `test_part2_card` / `test_notebook_sync` / `test_exam_state`：新链路；
  - `test_chat_history.py`：保存/恢复/上限/独立清空。
- 测试通过环境变量把 `BACKUP_DIR`、`CHAT_HISTORY_PATH`、`WORD_PROGRESS_PATH` 等
  指向临时目录，避免污染真实数据。
- 启动：`tools/launch.ps1`（隐藏窗口 + 健康检查 + 端口冲突检测 + 自动开浏览器）；
  `tools/stop-app.ps1` 按 `logs/app.pid` 停止；`start.bat` 会先清空 `audio_records/`，
  只适合调试。
- 备份：`tools/sync-data.ps1` 把 `data/*.json` 复制到 `.data-repo` 并 push 到私有仓库
  （独立 deploy key，见 `.ssh-data/`）。

## 11. 扩展点

| 想加什么 | 改哪里 |
| --- | --- |
| 新页面 | `app.py` 的 `PAGE_TABLE` + 新文件 + 工作台卡片 |
| 新娱乐角色 | 复制一个 `ChatPageSpec` 页面，指定 `prefix/memory_key/voice`，加入 `PAGE_TABLE` |
| 新候选来源 | `PrepBook` 加 `_xxx_items()`、`sync_candidates` 调用、`_SOURCES` 与 `source_key` 命名空间 |
| 新持久化数据 | 新模块用 `storage.load_json/save_json` + 模块级 `RLock` + 上限/清洗 + 测试 |
| 新 LLM 能力 | 走 `call_llm_json`，失败给 `fallback`；后台线程显式传 `provider/model` |
| 新评分口径 | 改 `IeltsRubric.py`，不要在每个 prompt 里各写一套 |

改完共享模块或页面后，至少跑一遍测试，并重启 App：Streamlit 不会重新 import `utils/`。
