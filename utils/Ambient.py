# utils/Ambient.py

"""背景音：全局播放器 + 选择记忆。

音频是 6 段 CC0 现场录音（雨、海浪、森林鸟鸣、溪流、风、夜虫），
已经裁成 60 秒、两端做了 2 秒交叉淡化，放在 static/ambient/ 下，
由 Streamlit 的静态目录服务；详见 static/ambient/SOURCES.md。

为什么不用 st.audio：Streamlit 每次 rerun / 切页面都会重建元素，音乐会被打断。
这里把播放器注入父页面（window.parent），用 window.__ieltsAmbient 去重，
并用 AudioBufferSourceNode 的 loop 做到无缝循环；切页面只更新参数、不重启音频。

选择保存在 data/ambient.json，下次打开继续用上一次的音轨和音量。
"""

import json
import logging
import os
import threading
from pathlib import Path

from utils.storage import save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = Path(
    os.getenv("AMBIENT_PATH") or (_PROJECT_ROOT / "data" / "ambient.json")
)
_LOCK = threading.RLock()

CATALOG = {
    "off": "关闭",
    "rain": "雨声",
    "waves": "海浪",
    "birds": "森林鸟鸣",
    "stream": "溪流",
    "wind": "风声",
    "crickets": "夜虫",
}
DEFAULT_STATE = {"track": "rain", "volume": 35}


def _default_state() -> dict:
    return dict(DEFAULT_STATE)


def load_state() -> dict:
    with _LOCK:
        if not STATE_PATH.exists():
            return _default_state()
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("背景音配置损坏，使用默认值：%s", STATE_PATH)
            return _default_state()
    if not isinstance(data, dict):
        return _default_state()
    track = data.get("track") if data.get("track") in CATALOG else DEFAULT_STATE["track"]
    try:
        volume = int(data.get("volume"))
    except (TypeError, ValueError):
        volume = DEFAULT_STATE["volume"]
    return {"track": track, "volume": max(0, min(100, volume))}


def save_state(track: str, volume: int) -> dict:
    state = {
        "track": track if track in CATALOG else DEFAULT_STATE["track"],
        "volume": max(0, min(100, int(volume))),
    }
    with _LOCK:
        save_json(STATE_PATH, {"version": 1, **state})
    return state


def render_controls() -> dict:
    """全站侧边栏里的一小块背景音控制。"""
    import streamlit as st

    state = load_state()
    tracks = list(CATALOG)
    with st.sidebar.expander(
        f"🎧 背景音 · {CATALOG[state['track']]}", expanded=False
    ):
        track = st.selectbox(
            "音轨",
            tracks,
            index=tracks.index(state["track"]),
            format_func=lambda key: CATALOG[key],
            key="ambient_track",
        )
        volume = st.slider(
            "音量", 0, 100, int(state["volume"]), 5, key="ambient_volume"
        )
        st.caption("选择会记住，下次打开继续用；切换页面不会中断。")
        st.caption("浏览器可能要求先点一下页面才会出声。")

    if track != state["track"] or int(volume) != int(state["volume"]):
        state = save_state(track, int(volume))
    return state


def render_player(track: str, volume: int) -> None:
    """注入/更新父页面里的播放器；同一音轨不会重启。"""
    import streamlit as st

    st.iframe(player_html(track, volume), height=1, width=1)


def player_html(track: str, volume: int) -> str:
    script = _SCRIPT.replace("__TRACK__", json.dumps(track)).replace(
        "__VOLUME__", str(max(0, min(100, int(volume))))
    )
    return f"<script>{script}</script>"


_SCRIPT = r"""
(function () {
  var track = __TRACK__;
  var volume = __VOLUME__;
  var win = window.parent;
  var doc = win.document;
  var key = "__ieltsAmbient";

  function controllerFor(w) {
    if (w[key]) return w[key];
    var AC = w.AudioContext || w.webkitAudioContext;
    if (!AC) return { set: function () {} };

    var ctx = new AC();
    var master = ctx.createGain();
    master.gain.value = 0;
    master.connect(ctx.destination);

    var buffers = {};
    var pending = {};
    var current = null;
    var currentName = "off";
    var token = 0;
    var gestureBound = false;
    var lastVolume = volume;

    function sourceUrl(name) {
      return "/app/static/ambient/" + name + ".mp3";
    }

    function load(name) {
      if (buffers[name]) return Promise.resolve(buffers[name]);
      if (pending[name]) return pending[name];
      pending[name] = fetch(sourceUrl(name))
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

    function stopCurrent(fadeSeconds) {
      if (!current) return;
      var old = current;
      current = null;
      var now = ctx.currentTime;
      old.gain.gain.cancelScheduledValues(now);
      old.gain.gain.setValueAtTime(Math.max(0.0001, old.gain.gain.value), now);
      old.gain.gain.linearRampToValueAtTime(0.0001, now + fadeSeconds);
      try {
        old.source.stop(now + fadeSeconds + 0.05);
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
          var gain = ctx.createGain();
          gain.gain.value = 0.0001;
          source.connect(gain).connect(master);
          source.start(0);
          gain.gain.linearRampToValueAtTime(1, ctx.currentTime + 0.9);
          current = { name: name, source: source, gain: gain };
          ctx.resume().catch(function () {});
        })
        .catch(function (error) {
          if (w.console) w.console.warn("ambient load failed", name, error);
        });
    }

    function setVolume(value) {
      lastVolume = value;
      var level = Math.max(0, Math.min(100, value)) / 100 * 0.9;
      master.gain.setTargetAtTime(level, ctx.currentTime, 0.15);
    }

    function hideStartHint() {
      if (!doc.getElementById) return;
      var existing = doc.getElementById("__ambient_start");
      if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
    }

    function showStartHint() {
      if (ctx.state === "running" || !doc.body || !doc.createElement) return;
      if (doc.getElementById && doc.getElementById("__ambient_start")) return;
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
            api.set(currentName === "off" ? track : currentName, lastVolume);
          })
          .catch(function () {});
        hideStartHint();
      };
      doc.body.appendChild(button);
    }

    ctx.onstatechange = function () {
      if (ctx.state === "running") hideStartHint();
    };
    setTimeout(showStartHint, 1500);

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

    var api = {
      set: function (name, value) {
        setVolume(value);
        if (name === currentName && (current || pending[name])) {
          if (ctx.state === "suspended") ctx.resume().catch(function () {});
          return;
        }
        currentName = name;
        token += 1;
        stopCurrent(0.35);
        if (name === "off") return;
        start(name);
        ctx.resume().catch(function () {});
        resumeOnGesture();
      }
    };
    w[key] = api;
    return api;
  }

  controllerFor(win).set(track, volume);
})();
"""
