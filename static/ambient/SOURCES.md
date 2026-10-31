# 背景音来源

背景音是 6 段真实环境录音，不是合成音。

- 原始录音来自 [Freesound](https://freesound.org/)，均为 **CC0 1.0**（公有领域贡献），可自由使用。
- 循环版本由 [omarchy-ambient](https://github.com/funcoder/omarchy-ambient) 从无损母带中选取、做响度匹配并交叉淡化。
- 本仓库在此基础上又做了：截取 60 秒、2 秒等功率交叉淡化、响度归一化（约 -20 dBFS RMS）、转码为 160 kbps MP3。

| 文件 | 用途 | 原录音 | 作者 | Freesound |
| --- | --- | --- | --- | --- |
| rain | 雨声 | Soft rain on a tile roof | richwise | [466241](https://freesound.org/s/466241/) |
| waves | 海浪 | Crashing Waves - Pacific Ocean | SecureSubset | [817075](https://freesound.org/s/817075/) |
| birds | 森林鸟鸣 | Forest quiet atmosphere with some birds | felix.blume | [414098](https://freesound.org/s/414098/) |
| stream | 溪流 | Relaxing River Sound | IceVFX | [722875](https://freesound.org/s/722875/) |
| wind | 风声 | Wind on bushes with muffled gust of wind, twig branch, close to desert ground | felix.blume | [711106](https://freesound.org/s/711106/) |
| crickets | 夜虫 | Crickets (close recording) | felix.blume | [476672](https://freesound.org/s/476672/) |

## 使用与替换

- 只要 `static/ambient-local/` 里有 mp3，App 就只从 `LOCAL_CATALOG` 里列出这个目录中实际存在的音轨；该目录为空时才用 `static/ambient/` 的 6 段内置录音。
- `static/ambient-local/` 是使用者的本机个人副本，已列入 `.gitignore`，不随仓库分发。
- 想换成自己的音频：把文件放进 `static/ambient-local/`，文件名用 `LOCAL_CATALOG` 里的 id（`stars`、`rain`、`sea`、`forest`、`fire`、`voyage`、`cafe`）；也可以直接替换 `static/ambient/<id>.mp3`。
- 本仓库只保留处理后的 60 秒 MP3，不包含 Freesound 的原始母带。

CC0 不要求署名；这里保留作者和来源，是为了可追溯，也方便替换。
