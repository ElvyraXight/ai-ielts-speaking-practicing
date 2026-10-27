# Third-party notices

## Word Atlas

- Repository: <https://github.com/designfuchen/word-atlas>
- Code: MIT License, Copyright (c) 2026 Word Atlas contributors.

`utils/Ambient.py` 里的背景音播放逻辑移植自该仓库的 `src/lib/sound.ts`：
AudioBuffer 循环、`loopStart`/`loopEnd` 裁掉 MP3 解码补白、2 秒淡入 / 1.2 秒淡出、
音量曲线，均按其实现改写为可注入 Streamlit 父页面的脚本。

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

### 素材授权

- 词库、插画、单词与例句录音：CC BY 4.0（见 `assets/word-atlas-LICENSE.txt`）。
- `public/sfx/` 下的环境声与配乐**不在该仓库的 CC BY 授权范围内**。
  本仓库不包含、也不分发这些文件；`static/ambient-local/` 是使用者本机的个人副本，
  已列入 `.gitignore`。

## 环境录音

`static/ambient/` 下的 6 段 CC0 录音来源见 `static/ambient/SOURCES.md`。
