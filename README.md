# AI IELTS Speaking

一个本地运行的雅思口语练习 App：Streamlit 界面 + Ollama（默认 `qwen2.5:7b`）/ DeepSeek API + Whisper 语音识别 + edge-tts 朗读。

## 功能

| 页面 | 能做什么 |
| --- | --- |
| 入口 | 总览页，进入各练习 / 娱乐模式 |
| 严肃话题（全真模拟） | AI 考官按雅思流程提问和追问；实时给语法纠错、润色和 Band 8 参考回答；支持麦克风输入和朗读 |
| 自由聊天 | 自定义聊天对象人设，日常闲聊；附语法、润色、地道表达建议 |
| 讲个故事（Part 2） | 生成标准 Cue Card；打字或录音讲故事；时态语法纠错、Band 7 改写答案、Band 8 参考范文；可朗读 |
| AI 老师 | 对话式雅思老师；自动读取当前 Part 2 题卡和故事；改答案、讲结构、模拟 Part 3 追问 |
| 笔记本 | 积累单词 / 词组 / 例句；支持搜索、标签、修改、删除、随机复习；各练习页侧边栏可随手收藏 |
| 猫娘小屋 | 角色扮演聊天（英文回复，中文提问会自动翻译） |
| 心理咨询 | 心理咨询师角色对话 |
| 学业导师 | 电子信息 / 论文方向导师角色对话 |

## 运行

1. 安装 Python 3.12+，并在系统里安装 **ffmpeg**（Whisper 转写需要）。
2. 安装依赖：
   ```powershell
   pip install -r requirements.txt
   ```
3. 选择模型：
   - **在线（推荐）**：在 `config/.env.local` 填 `DEEPSEEK_API_KEY`，见下方「使用 DeepSeek 在线 API」。
   - **本地**：安装并启动 [Ollama](https://ollama.com)，然后 `ollama pull qwen2.5:7b`。
4. 启动 App（任选一种）：
   - 双击 `start.bat`
   - 或命令行：
     ```powershell
     .\.venv\Scripts\activate
     python -m streamlit run app.py
     ```
5. 打开 http://localhost:8501

## 模型配置

配置文件是 `config/.env`（本地密钥建议放 `config/.env.local`，已被 `.gitignore` 忽略）。

```ini
# auto: 配了 DEEPSEEK_API_KEY 就用 DeepSeek，否则用 Ollama
LLM_PROVIDER=auto

DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash

OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=qwen2.5:7b
```

说明：

- **全站页面**（严肃话题、自由聊天、讲个故事、AI 老师、娱乐小屋）统一使用上面的配置。
- 配了 `DEEPSEEK_API_KEY` 后，所有页面都走 DeepSeek 在线 API；没有 Key 时回退本地 Ollama。
- 修改 `.env` 后需要重启 App。
- 页面顶部会显示当前模型，例如 `🤖 当前模型：DeepSeek · deepseek-flash`。

### 使用 DeepSeek 在线 API

1. 打开 <https://platform.deepseek.com/>，登录并充值（API 按量计费，先充少量即可）。
2. 左侧「API keys」→ 创建 API key，复制 `sk-...`（只显示一次）。
3. 打开 `config/.env.local`，填：
   ```ini
   DEEPSEEK_API_KEY=sk-你的key
   ```
4. 重启 App（关闭 Streamlit 窗口后重新双击 `start.bat`）。
5. 页面顶部显示 `🤖 当前模型：DeepSeek · deepseek-flash` 即生效。

## Token 与费用（大致）

实测（`deepseek-flash`，已关闭 thinking）：

| 操作 | 调用次数 | 输入 token | 输出 token | 低峰成本 |
|---|---:|---:|---:|---:|
| Part 2 判题（语法 + 改写 + 范文） | 2 | 约 1,000 | 约 650 | 约 0.4 分 |
| 严肃话题一轮 | 2 | 约 500 | 约 260 | 约 0.2 分 |
| 自由聊天一轮 | 2 | 约 350 | 约 120 | 约 0.1 分 |
| AI 老师一轮 | 1 | 约 450 | 约 220 | 约 0.15 分 |

- 费用按 DeepSeek 官方 `deepseek-flash` 价格估算，低峰约为高峰的一半。
- 已把语法点评与改写合并成一次调用；严肃话题由 5 次降为 2 次，自由聊天由 4 次降为 2 次。
- 改写答案过短时会额外补一次扩写，所以 Part 2 偶尔是 3 次调用。
- 默认关闭 thinking，避免额外推理 token。

## 笔记本

- 入口：左侧「练习 → 笔记本」，或首页的「📓 单词 / 词组笔记本」。
- 各练习页（严肃话题、自由聊天、讲个故事、AI 老师）侧边栏都有「➕ 加入笔记本」，随手保存单词、词组和例句。
- 支持搜索、标签筛选、修改、删除、随机复习和导出 JSON。
- 数据保存在 `data/notebook.json`，已加入 `.gitignore`；重启 App 不会丢。

## 目录

```
app.py                 页面导航
course/dashboard.py    入口页
chats/                 各功能页面（Part2、Tutor、Notebook 等）
utils/                 模型调用、语音识别/合成、提示词、笔记本数据层
config/.env            模型配置
data/notebook.json     笔记本数据（自动创建，已 gitignore）
start.bat              Windows 一键启动
audio_records/         生成的语音（启动时自动清理）
```

## 语音

- 识别：OpenAI Whisper `base` 模型，按需加载。
- 朗读：`edge-tts`，英式发音 `en-GB-RyanNeural`。

## License

见 [LICENSE](LICENSE)。
