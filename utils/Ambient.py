# utils/Ambient.py

"""背景音：全局播放器 + 选择记忆。

播放逻辑按 Word Atlas 的开源实现移植：
https://github.com/designfuchen/word-atlas/blob/main/src/lib/sound.ts
（MIT License，Copyright (c) 2026 Word Atlas contributors，见 THIRD_PARTY_NOTICES.md）

实现要点：
- 控制器注入到父页面（window.parent）执行，不依赖 Streamlit 组件 iframe 的生命周期；
  切页面、重建 iframe 都不会影响正在播放的音频。
- AudioBufferSourceNode loop，loopStart/loopEnd 各裁掉 0.06 秒解码补白，循环无缝。
- 切歌淡出 1.2 秒、淡入 2 秒；同一音轨调音量 0.4 秒。

音频查找顺序：
1. static/ambient-local/<id>.mp3 —— 本机音色（词光那套），已 gitignore，不提交；
2. static/ambient/<id>.mp3 —— 仓库自带的 CC0 录音，作为默认/回退。

选择保存在 data/ambient.json，下次打开继续用上一次的音轨和音量。
"""

import json
import logging
import os
import threading
from pathlib import Path

from utils.storage import load_json, save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = Path(
    os.getenv("AMBIENT_PATH") or (_PROJECT_ROOT / "data" / "ambient.json")
)
LOCAL_DIR = Path(
    os.getenv("AMBIENT_LOCAL_DIR") or (_PROJECT_ROOT / "static" / "ambient-local")
)
BUNDLED_DIR = Path(
    os.getenv("AMBIENT_BUNDLED_DIR") or (_PROJECT_ROOT / "static" / "ambient")
)
_LOCK = threading.RLock()

# 顺序与词光 AMBIENCE 一致
LOCAL_CATALOG = {
    "stars": "星空音乐",
    "rain": "雨天图书馆",
    "sea": "清晨海岸",
    "forest": "林间早晨",
    "fire": "夜晚壁炉",
    "voyage": "远航船舱",
    "cafe": "安静咖啡馆",
}
BUNDLED_CATALOG = {
    "rain": "雨声",
    "waves": "海浪",
    "birds": "森林鸟鸣",
    "stream": "溪流",
    "wind": "风声",
    "crickets": "夜虫",
}
DEFAULT_STATE = {"track": "rain", "volume": 35}


def _files(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        return {}
    return {path.stem: path for path in sorted(directory.glob("*.mp3"))}


def catalog() -> dict[str, str]:
    """按实际存在的文件给出可选音轨。"""
    local = _files(LOCAL_DIR)
    if local:
        tracks = {key: label for key, label in LOCAL_CATALOG.items() if key in local}
    else:
        bundled = _files(BUNDLED_DIR)
        tracks = {key: label for key, label in BUNDLED_CATALOG.items() if key in bundled}
    return {"off": "关闭", **tracks}


def track_urls() -> dict[str, str]:
    local = _files(LOCAL_DIR)
    bundled = _files(BUNDLED_DIR)
    urls = {}
    for key in catalog():
        if key == "off":
            continue
        if key in local:
            urls[key] = f"/app/static/ambient-local/{local[key].name}"
        elif key in bundled:
            urls[key] = f"/app/static/ambient/{bundled[key].name}"
    return urls


def _default_track() -> str:
    tracks = [key for key in catalog() if key != "off"]
    if "rain" in tracks:
        return "rain"
    return tracks[0] if tracks else "off"


def load_state() -> dict:
    with _LOCK:
        data = load_json(STATE_PATH, None)
    if not isinstance(data, dict):
        return {"track": _default_track(), "volume": DEFAULT_STATE["volume"]}
    tracks = catalog()
    track = data.get("track") if isinstance(data, dict) else None
    if track not in tracks:
        track = _default_track()
    try:
        volume = int(data.get("volume"))
    except (TypeError, ValueError):
        volume = DEFAULT_STATE["volume"]
    return {"track": track, "volume": max(0, min(100, volume))}


def save_state(track: str, volume: int) -> dict:
    tracks = catalog()
    state = {
        "track": track if track in tracks else _default_track(),
        "volume": max(0, min(100, int(volume))),
    }
    with _LOCK:
        save_json(STATE_PATH, {"version": 1, **state})
    return state


def _persist_from_widgets() -> None:
    """控件一改就落盘。

    回调在脚本重跑之前执行，所以 app.py 里的播放器能在同一轮读到新音轨。
    """
    import streamlit as st

    track = st.session_state.get("ambient_track")
    volume = st.session_state.get("ambient_volume")
    if track in catalog() and isinstance(volume, (int, float)):
        save_state(track, int(volume))


def render_picker() -> dict:
    """首页右上角的背景音按钮，和模型切换放在一起。"""
    import streamlit as st

    state = load_state()
    tracks = catalog()
    options = list(tracks)
    if len(options) <= 1:
        st.caption("🎧 无可用音轨")
        return state

    label = tracks.get(state["track"], "关闭")
    with st.popover(
        f"🎧 {label}",
        help="背景音 · 环境声",
        use_container_width=True,
    ):
        st.caption(f"环境声 · 专注陪伴（当前：{label}）")
        st.selectbox(
            "音轨",
            options,
            index=options.index(state["track"]),
            format_func=lambda key: tracks[key],
            key="ambient_track",
            on_change=_persist_from_widgets,
        )
        st.slider(
            "音量",
            0,
            100,
            int(state["volume"]),
            5,
            key="ambient_volume",
            on_change=_persist_from_widgets,
        )
        st.caption("选择会记住；切换页面不会中断。")
        st.caption("浏览器可能要求先点一下页面才会出声。")
    return state


def render_player(track: str, volume: int) -> None:
    """注入/更新父页面里的播放器；同一音轨不会重启。"""
    import streamlit as st

    st.iframe(player_html(track, volume), height=1, width=1)


def player_html(track: str, volume: int) -> str:
    volume = max(0, min(100, int(volume)))
    config = json.dumps(
        {"urls": track_urls(), "volume": volume}, ensure_ascii=False
    )
    return f"""
<script type="text/plain" id="__ambient_controller">{_CONTROLLER}</script>
<script>
(function () {{
  var w = window.parent;
  w.__ambientConfig = {config};
  if (!w.__ieltsAmbient) {{
    var source = document.getElementById("__ambient_controller").textContent;
    var node = w.document.createElement("script");
    node.textContent = source;
    (w.document.head || w.document.documentElement).appendChild(node);
  }}
  if (w.__ieltsAmbient) w.__ieltsAmbient.set({json.dumps(track)}, {volume});
}})();
</script>
"""


# 在父页面（window）里执行，而不是在 Streamlit 组件的 iframe 里。
# 这样 iframe 被重建/销毁时，AudioContext、解码缓存和定时器都还在。
_CONTROLLER = r"""
(function () {
  var w = window;
  if (w.__ieltsAmbient) return;
  var cfg = w.__ambientConfig || {};
  var urls = cfg.urls || {};
  var doc = w.document;
  var AC = w.AudioContext || w.webkitAudioContext;
  if (!AC) {
    w.__ieltsAmbient = { set: function () {} };
    return;
  }

  var ctx = new AC();
  var buffers = {};
  var pending = {};
  var current = null;
  var currentName = "off";
  var lastRequested = "off";
  var token = 0;
  var gestureBound = false;
  var lastVolume = cfg.volume || 0;

  function level() {
    return Math.max(0, Math.min(100, lastVolume)) / 100 * 0.9;
  }

  function fadeTo(gainNode, value, seconds) {
    var now = ctx.currentTime;
    gainNode.gain.cancelScheduledValues(now);
    gainNode.gain.setValueAtTime(gainNode.gain.value, now);
    gainNode.gain.linearRampToValueAtTime(value, now + seconds);
  }

  function load(name) {
    if (buffers[name]) return Promise.resolve(buffers[name]);
    if (pending[name]) return pending[name];
    var url = urls[name];
    if (!url) return Promise.reject(new Error("no url for " + name));
    pending[name] = fetch(url)
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.arrayBuffer();
      })
      .then(function (data) {
        return new Promise(function (resolve, reject) {
          ctx.decodeAudioData(
            data,
            function (buffer) {
              buffers[name] = buffer;
              resolve(buffer);
            },
            reject
          );
        });
      })
      .catch(function (error) {
        delete pending[name];
        throw error;
      });
    return pending[name];
  }

  function stopCurrent() {
    if (!current) return;
    var old = current;
    current = null;
    fadeTo(old.gain, 0, 1.2);
    try {
      old.source.stop(ctx.currentTime + 1.3);
    } catch (e) {}
  }

  function start(name) {
    var myToken = ++token;
    load(name)
      .then(function (buffer) {
        if (myToken !== token || currentName !== name) return;
        var source = ctx.createBufferSource();
        source.buffer = buffer;
        source.loop = true;
        source.loopStart = 0.06;
        source.loopEnd = Math.max(0.12, buffer.duration - 0.06);
        var gain = ctx.createGain();
        gain.gain.value = 0;
        source.connect(gain).connect(ctx.destination);
        source.start(0, 0.06);
        current = { name: name, source: source, gain: gain };
        fadeTo(gain, level(), 2);
        ctx.resume().catch(function () {});
      })
      .catch(function (error) {
        if (w.console) w.console.warn("ambient load failed", name, error);
      });
  }

  function hideStartHint() {
    var existing = doc.getElementById("__ambient_start");
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
  }

  function showStartHint() {
    if (ctx.state === "running" || !doc.body) return;
    if (doc.getElementById("__ambient_start")) return;
    var button = doc.createElement("button");
    button.id = "__ambient_start";
    button.textContent = "🔊 点击开启背景音";
    button.style.cssText =
      "position:fixed;right:18px;bottom:18px;z-index:999999;padding:8px 14px;" +
      "border-radius:12px;border:1px solid #D8BFD8;background:#E6E6FA;" +
      "color:#4B0082;font:13px/1.4 system-ui,sans-serif;cursor:pointer;" +
      "box-shadow:0 3px 12px rgba(0,0,0,.18)";
    button.onclick = function () {
      ctx.resume()
        .then(function () {
          api.set(lastRequested === "off" ? "rain" : lastRequested, lastVolume);
        })
        .catch(function () {});
      hideStartHint();
    };
    doc.body.appendChild(button);
  }

  function resumeOnGesture() {
    if (ctx.state !== "suspended" || gestureBound) return;
    gestureBound = true;
    var resume = function () {
      ctx.resume().catch(function () {});
      doc.removeEventListener("pointerdown", resume, true);
      doc.removeEventListener("keydown", resume, true);
      gestureBound = false;
    };
    doc.addEventListener("pointerdown", resume, true);
    doc.addEventListener("keydown", resume, true);
  }

  ctx.onstatechange = function () {
    if (ctx.state === "running") hideStartHint();
  };
  setTimeout(showStartHint, 1500);

  var api = {
    set: function (name, value) {
      lastVolume = value;
      lastRequested = name;
      if (name === currentName && (current || pending[name])) {
        if (current) fadeTo(current.gain, level(), 0.4);
        if (ctx.state === "suspended") ctx.resume().catch(function () {});
        return;
      }
      currentName = name;
      token += 1;
      stopCurrent();
      if (name === "off") return;
      start(name);
      ctx.resume().catch(function () {});
      resumeOnGesture();
    }
  };

  w.__ieltsAmbient = api;
})();
"""
