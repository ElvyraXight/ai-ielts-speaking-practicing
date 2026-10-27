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

如替换成自己的音频，保持文件名不变即可（`static/ambient/<id>.mp3`）。
