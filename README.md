# AI IELTS Speaking

一个跑在你自己电脑上的雅思口语练习工作台。Streamlit 做界面，DeepSeek API 或本地 Ollama 做对话，
Whisper 转写录音，edge-tts 朗读。单词进度、笔记、计划、聊天记录都写在本地 `data/`。

## Fork 说明

本项目 fork 自 [LegendZDY/AI-IELTS-Speaking](https://github.com/LegendZDY/AI-IELTS-Speaking)。

- **上游**：Streamlit + autogen 的雅思口语练习原型，MIT 许可，Copyright © 2024 De Ying Zhang
- **本仓库**：在上游基础上重写了导航与页面外壳，补上背单词、笔记本、表达库和老师计划链路，
  并加入考试状态机与考场内的「老师帮帮我」
- **版权**：上游部分归原作者，新增与修改部分 Copyright © 2026 ElvyraXight，两者都按 MIT 发布，
  见 [LICENSE](LICENSE)；词库与环境音的授权见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## 页面

| 栏目 | 页面 | 做什么 |
| --- | --- | --- |
| — | 主页 | 今日打卡（新词 / 复习 / 表达 / 课程计划）与三个入口 |
| 练习 | 严肃话题 | 和考官对话：开场、Part 1 一轮 8 题、Part 3 一轮 6 题，每轮同时给语法纠错、表达润色、高分参考 |
| 练习 | 自由聊天 | 自定义聊天对象，闲聊里带语法、润色和地道说法 |
| 练习 | 讲个故事 | Part 2 题卡与草稿会存住，给 Band 7 改写和 Band 8.5 范文 |
| 练习 | 背单词 | 7,298 条雅思词条，按考试日期排每日词量，三阶段回忆 + 间隔重复 |
| 工具 | 雅思老师 | 从备课本排出本课计划，逐点带练，另有裁判判定计划点是否完成 |
| 工具 | 笔记本 | 单词 / 词组、表达（中文意图 → 地道说法）、仓库便签 |
| 工具 | 查资料 | 一个干净的对话 AI，不带记忆、语音和计划 |
| 娱乐 | 日常闲聊 | 温柔风趣的聊天对象，跨会话记得你说过的事 |
| 娱乐 | 猫娘小屋 | 角色扮演，英文回复 |
| 娱乐 | 心理咨询 | 咨询师角色，每次会话留一份诊疗笔记 |
| 娱乐 | 学业导师 | 电子信息 / 论文方向导师，留指导记录 |
| 隐藏 | 老师帮帮我 | 考场内临时求助，不推进考试；结束这段帮助时把过程写进学习档案 |

除页面之外的几件小事：侧栏「随手查」随时英译中、中文给英文说法；每个练习页都能把生词和
好句子收进笔记本；`Ctrl+Enter` 直接发送；背景音可换；聊天记录刷新不丢。

## 运行

需要 **Python 3.12+** 和 **ffmpeg**（Whisper 转写要用，装完加进 PATH）。

```powershell
git clone https://github.com/ElvyraXight/ai-ielts-speaking-practicing.git
cd ai-ielts-speaking-practicing
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.lock.txt
```

模型二选一：

```ini
# config/.env.local（已被 gitignore，优先于 config/.env）
DEEPSEEK_API_KEY=sk-你的key
```

或者用本地模型：装 [Ollama](https://ollama.com) 后 `ollama pull qwen2.5:7b`。

然后启动：

```powershell
start.bat
```

它会打开 <http://localhost:8501>。想要后台启动、不弹黑窗口，用
`powershell -ExecutionPolicy Bypass -File tools\launch.ps1`。

## 配置

配置写在 `config/.env`，个人密钥放 `config/.env.local`（覆盖前者）。

| 变量 | 说明 |
| --- | --- |
| `LLM_PROVIDER` | `auto` / `deepseek` / `ollama`，`auto` 表示有 Key 就走在线 |
| `DEEPSEEK_API_KEY` | DeepSeek 的 Key，没填就走本地 Ollama |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 默认 `deepseek-flash` |
| `OLLAMA_URL` / `OLLAMA_MODEL` | 本地接口与默认模型 `qwen2.5:7b` |
| `WHISPER_MODEL` / `WHISPER_COMPUTE_TYPE` | 识别模型与精度，默认 `base` / `int8` |

主页右上角可以随时切换模型，选择会记住。

## 目录

```
app.py                 入口：页面注册、全站样式、侧栏、模型与背景音
course/dashboard.py    工作台
chats/                 12 个页面
utils/                 38 个模块：模型调用、考试状态、计划与裁判、记忆、词库、存储、语音
docs/                  架构说明、开发记录、验收手册
tools/                 启动 / 停止 / 备份 / 生成快捷方式的 PowerShell 脚本
assets/                内置词库与应用图标
static/ambient/        6 段 CC0 背景音
data/                  本地数据，首次运行自动创建
```

## 语音

识别优先用 `faster-whisper`，加载失败自动回退 `openai-whisper`；朗读用 `edge-tts`，
默认英式男声 `en-GB-RyanNeural`，其余角色各配一种音色。生成的音频只保留当天。

## License

[MIT](LICENSE)。上游原作者的版权声明保留在许可证里。
