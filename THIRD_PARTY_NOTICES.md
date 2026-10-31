# Third-party notices / 第三方声明

本文件列出本仓库用到的第三方代码、词库与素材，以及各自的授权。
本仓库自身的代码许可见 [LICENSE](LICENSE)；fork 关系与版权归属见
[README 的「版权与第三方素材」](README.md#版权与第三方素材)。

## 1. 上游项目与代码许可

| 范围 | 版权 | 许可 |
| --- | --- | --- |
| 上游 [LegendZDY/AI-IELTS-Speaking](https://github.com/LegendZDY/AI-IELTS-Speaking) | Copyright © 2024 De Ying Zhang | MIT |
| 本仓库的重写与新增 | Copyright © 2026 ElvyraXight | MIT |

上游的 MIT 许可证保留在 [LICENSE](LICENSE)（本仓库补了一行修改部分的版权，许可条款本身未改）。

## 2. Word Atlas

- 开源仓库：<https://github.com/designfuchen/word-atlas>（站点 <https://0xlei.tech/words/>）
- 代码许可：MIT License，Copyright (c) 2026 Word Atlas contributors.
- 词库内容许可：**CC BY 4.0**，署名 **Word Atlas contributors**。

### 本仓库用到的地方

| 位置 | 内容 | 授权 |
| --- | --- | --- |
| `assets/word-atlas.json` | 7,298 条雅思词库，含 CEFR 分级、释义、例句、搭配 | 内容 CC BY 4.0 |
| `utils/Ambient.py` | 背景音播放逻辑，移植自 `src/lib/sound.ts` | 代码 MIT |
| `chats/Words.py`、`utils/WordAtlas.py` | 背单词页「考试计划」：目标分数 → CEFR 范围（7.5 → B2–C1，3,735 词）、考试日期 → 剩余天数、最后 7 天只复习、每日新词 = `ceil(剩余未学 / max(1, 天数 - 7))`；对话框与灰色说明也按其同名功能复刻 | 代码 MIT |

### 修改说明

- 本仓库把词库整理为 `assets/word-atlas.json` 单文件，并按本应用的字段读取；词库文本内容的使用遵守 CC BY 4.0。
- 「考试计划」的分数区间和换算法按其公开实现用 Python 重写；词库的 CEFR 分级与词条数量决定参考范围的数字。
- `utils/Ambient.py` 的背景音播放逻辑移植自该仓库的 `src/lib/sound.ts`：
  AudioBuffer 循环、`loopStart`/`loopEnd` 裁掉 MP3 解码补白、2 秒淡入 / 1.2 秒淡出、
  音量曲线，均按其实现改写为可注入 Streamlit 父页面的脚本。
- 本仓库**不包含** Word Atlas 的插画、单词/例句录音或 `public/sfx/` 下的环境声与配乐；
  这些不在本仓库的分发范围内。

### Word Atlas MIT 许可证原文

```text
MIT License

Copyright (c) 2026 Word Atlas contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

词的授权原文见 [`assets/word-atlas-LICENSE.txt`](assets/word-atlas-LICENSE.txt)。

## 3. 环境录音

`static/ambient/` 下的 6 段录音均为 **CC0 1.0**（公有领域贡献）。原始录音来自 Freesound，
循环版本由 [omarchy-ambient](https://github.com/funcoder/omarchy-ambient) 选取和处理；
本仓库再截取 60 秒、做等功率交叉淡化、响度归一化，并转成 160 kbps MP3。

| 文件 | 原录音 | 作者 | Freesound |
| --- | --- | --- | --- |
| rain | Soft rain on a tile roof | richwise | [466241](https://freesound.org/s/466241/) |
| waves | Crashing Waves - Pacific Ocean | SecureSubset | [817075](https://freesound.org/s/817075/) |
| birds | Forest quiet atmosphere with some birds | felix.blume | [414098](https://freesound.org/s/414098/) |
| stream | Relaxing River Sound | IceVFX | [722875](https://freesound.org/s/722875/) |
| wind | Wind on bushes with muffled gust of wind | felix.blume | [711106](https://freesound.org/s/711106/) |
| crickets | Crickets (close recording) | felix.blume | [476672](https://freesound.org/s/476672/) |

CC0 不要求署名；这里保留作者和来源，是为了可追溯，也方便替换。完整清单见
[`static/ambient/SOURCES.md`](static/ambient/SOURCES.md)。

`static/ambient-local/` 是使用者本机的自定义音轨，已列入 `.gitignore`，不随仓库分发，
也不在 CC0 声明范围内。

## 4. 运行时依赖

| 依赖 | 许可 | 用途 |
| --- | --- | --- |
| Streamlit | Apache-2.0 | Web 界面 |
| OpenAI Whisper | MIT | 语音识别回退方案 |
| faster-whisper | MIT | 语音识别主方案 |
| CTranslate2 | MIT | faster-whisper 的推理后端 |
| PyAV | BSD | 音频解码 |
| edge-tts | LGPL-3.0 | 在线朗读 |
| python-dotenv | BSD-3-Clause | 读取 `config/.env` |
| requests | Apache-2.0 | LLM / Ollama 请求 |

这些包以独立依赖方式安装，未修改其源码；各自许可见安装包元数据。
`edge-tts` 是 LGPL-3.0，如果要再分发打包后的应用，请自行确认 LGPL 对动态链接和源码提供的要求。

本仓库不打包 Whisper 模型权重或 Ollama 模型；它们的许可/服务条款由各自项目提供。
朗读音频由 edge-tts 调用微软 Edge 在线语音合成生成，只作本机缓存，不随仓库分发。

## 5. 商标与免责声明

- IELTS® 是 British Council、IDP: IELTS Australia 与 Cambridge University Press & Assessment 的注册商标。
  本项目与雅思考试主办方无关联，也未获其背书。
- 词库不是官方雅思词表；AI 的纠错、改写、评分与范文只用于练习参考，不代表官方评分，也不保证考试分数。
- DeepSeek、Ollama、Streamlit、Microsoft Edge 等名称是其各自所有者的商标，仅用于说明技术栈。
