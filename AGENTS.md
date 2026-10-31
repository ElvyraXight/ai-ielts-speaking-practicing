# AGENTS.md

本文件给在本仓库工作的 AI 代理看。人类可读版本见 `README.md`。

## 硬性规则：改完自动重启一次 App

用户的要求：**代码一改完就自动重启 App，让改动立刻生效，不要每次再问要不要重启。**

- **时机**：一轮修改全部改完、汇报结果之前，重启**一次**（改多个文件也只重启一次）。
- **范围**：改了会影响 App 运行的文件（`.py`、`.css`、`static/`、`config/`）就重启；只改 `*.md` 之类文档不必重启。
- **不要为“要不要重启”再问用户**，直接做。只有改什么不确定时才问。

### 怎么重启：停 → 后台任务起 → 另开命令验活

```powershell
# 1) 停
powershell -NoProfile -ExecutionPolicy Bypass -File tools\stop-app.ps1
```

```
# 2) 起：必须用 run_in_background=true 的常驻后台任务，前台命令里起的进程会被回收
& "<repo>\.venv\Scripts\python.exe" -m streamlit run app.py --server.headless=true --server.port=8501 --browser.gatherUsageStats=false 1> logs\app.out.log 2> logs\app.err.log
```

```powershell
# 3) 另开一条命令验活，并把监听进程 pid 写进 logs\app.pid 供 stop-app.ps1 使用
(Invoke-WebRequest 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -TimeoutSec 5).StatusCode
netstat -ano | Select-String ':8501.*LISTENING'
```

- 验收标准：**health 返回 200**。不是 200 就看 `logs\app.err.log`，不要假装成功。
- `logs\app.err.log` 里 Streamlit 的日志会被 Windows PowerShell 包一层 `NativeCommandError`
  报错壳，内容是完整的，看带时间戳的那行即可。
- 为什么会这样：在工具的前台命令里启动（不管是 `launch.ps1`、`Start-Process` 还是
  `explorer.exe` 快捷方式），命令结束时子进程会被连带收掉，表现是“提示 STARTED 但端口空掉”。
  只有常驻后台任务里的 Streamlit 能活下来。
- `App` 跟着后台任务走：本次会话结束任务停掉，App 也停，用户双击桌面图标即可。

### 后台任务被环境回收：不用管，也不要修

**用户明确说过：这件事不用处理。** 常见表现：

- 突然收到 `background job ... finished [status: completed, exit code: 1]`；
- App 进程在用户没操作的情况下消失，或者隔几秒又自己起来；
- `logs\app.err.log` 里只有一行 `Uvicorn server started`，没有任何 Traceback。

这是运行环境会回收后台任务/子进程导致的，**不是代码 bug**。所以：

- 不要为它去改代码、加守护进程、加自动拉起、改启动方式、排查进程树或 Windows 事件日志；
- 更不要把"App 突然没了"当成自己的改动弄坏了，去回滚或改架构；
- 用户还在用 App 时遇到这种情况，最多按上面的「停 → 后台任务起 → 验活」重启一次，
  确认 health 200 就继续手头的事；用户没说要查就不用解释一堆。

只有一种情况要当真：health 一直不是 200、或 `logs\app.err.log` 里有真实 Traceback——
那才是代码问题，按正常流程排查。

### 用户自己的入口（不要改）

- 桌面 `C:\Users\ElvyraXight\Desktop\AI IELTS Speaking.lnk` → `tools\launch.ps1`，是用户日常双击用的，
  行为是隐藏启动 + 自动开浏览器。代理重启时不必走它，但也不要修改/删除它。
- 仓库根目录的 `AI IELTS Speaking.lnk`、`Stop App.lnk` 同理，是给用户的。

### 禁止：不要用 `start.bat` 重启

`start.bat` 第 5 行会 `del /q "audio_records\*.*"`，**清空 `audio_records/` 里的语音文件（TTS 与单词发音缓存）**。
除非用户明确说要清这些文件，永远不要用它起 App。

## 拿不准就问

- 用户明确要求：**只要有一点点不确定，就先问，不要猜着改。**
- 特别是这些地方容易猜错：改哪个页面/哪个区块、改成什么样、要不要动 `data/` 下的用户数据、
  要不要保留旧布局与旧 key、是否要同步改测试。

## 环境

- Python 3.12，虚拟环境在 `.venv`（用 `.venv\Scripts\python.exe`，不要用系统 python）。
- Streamlit 服务端口 **8501**，PID 记在 `logs\app.pid`。
- 用户数据在 `data/`，聊天记录在 `data/chat_history.json`，均有自动备份；改动前先确认。
- 后台启动的日志：`logs\app.out.log`、`logs\app.err.log`。

## 代码地图

| 路径 | 内容 |
| --- | --- |
| `app.py` | 入口、页面注册、全站 CSS、侧边栏、模型选择、背景音 |
| `course/dashboard.py` | 工作台：今日打卡、练习 / 工具 / 娱乐 三块入口 |
| `chats/` | 12 个页面脚本：严肃话题、自由聊天、讲个故事、背单词、雅思老师、笔记本、查资料、四个娱乐页、老师帮帮我 |
| `utils/` | 38 个领域模块：状态机、模型调用、计划/裁判、记忆、词库、表达库、存储、语音 |
| `tests/` | 20 个文件、322 个 `unittest` 用例；`.\.venv\Scripts\python.exe -m unittest discover -s tests -q` |
| `docs/` | 架构说明、开发记录、用户验收手册、截图清单 |
