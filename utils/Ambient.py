# utils/Ambient.py

"""背景音：全局播放器 + 选择记忆。

为什么不用 st.audio：Streamlit 每次 rerun / 切页面都会重建元素，音乐会被打断。
这里把播放器注入父页面（window.parent），并用 window.__ieltsAmbient 去重，
所以切换页面只更新参数、不重启音频。

音轨是 Web Audio 实时合成的，不依赖外部音频文件，离线可用。
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
    "sea": "海浪",
    "fire": "壁炉",
    "forest": "森林",
    "cafe": "咖啡馆",
    "night": "深夜书桌",
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

    var currentTrack = "off";
    var current = null;
    var buffers = {};
    var gestureBound = false;

    function noise(kind, seconds) {
      var cacheKey = kind + ":" + seconds;
      if (buffers[cacheKey]) return buffers[cacheKey];
      var length = Math.floor(ctx.sampleRate * seconds);
      var buffer = ctx.createBuffer(1, length, ctx.sampleRate);
      var data = buffer.getChannelData(0);
      var last = 0, b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
      for (var i = 0; i < length; i++) {
        var white = Math.random() * 2 - 1;
        if (kind === "brown") {
          last = (last + 0.02 * white) / 1.02;
          data[i] = last * 3.2;
        } else if (kind === "pink") {
          b0 = 0.99886 * b0 + white * 0.0555179;
          b1 = 0.99332 * b1 + white * 0.0750759;
          b2 = 0.96900 * b2 + white * 0.1538520;
          b3 = 0.86650 * b3 + white * 0.3104856;
          b4 = 0.55000 * b4 + white * 0.5329522;
          b5 = -0.7616 * b5 - white * 0.0168980;
          data[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362) * 0.09;
          b6 = white * 0.115926;
        } else {
          data[i] = white * 0.55;
        }
      }
      buffers[cacheKey] = buffer;
      return buffer;
    }

    function filter(type, freq, q) {
      var node = ctx.createBiquadFilter();
      node.type = type;
      node.frequency.value = freq;
      if (q !== undefined) node.Q.value = q;
      return node;
    }

    function noiseSource(kind, gainValue, sink) {
      var src = ctx.createBufferSource();
      src.buffer = noise(kind, 3);
      src.loop = true;
      var gain = ctx.createGain();
      gain.gain.value = gainValue;
      src.connect(gain);
      src.start(0);
      if (sink) sink.push(src);
      return gain;
    }

    function lfo(param, freq, depth) {
      var osc = ctx.createOscillator();
      osc.frequency.value = freq;
      var amp = ctx.createGain();
      amp.gain.value = depth;
      osc.connect(amp);
      amp.connect(param);
      osc.start(0);
      return osc;
    }

    function build(name) {
      var out = ctx.createGain();
      out.gain.value = 0;
      out.connect(master);
      var sources = [];
      var timers = [];
      var nodes = [out];

      function keep(node) { nodes.push(node); return node; }
      function timer(fn, ms, repeat) {
        var id = repeat ? setInterval(fn, ms) : setTimeout(fn, ms);
        timers.push(id);
        return id;
      }

      if (name === "rain") {
        var rainFilter = keep(filter("lowpass", 1600));
        var rainHigh = keep(filter("highpass", 400));
        noiseSource("white", 0.22, sources).connect(rainHigh).connect(rainFilter).connect(out);
        sources.push(keep(lfo(rainFilter.frequency, 0.08, 260)));
      } else if (name === "sea") {
        var seaFilter = keep(filter("lowpass", 520));
        noiseSource("brown", 0.20, sources).connect(seaFilter).connect(out);
        out.gain.value = 0.85;
        sources.push(keep(lfo(out.gain, 0.06, 0.22)));
      } else if (name === "fire") {
        var fireFilter = keep(filter("lowpass", 700));
        noiseSource("brown", 0.16, sources).connect(fireFilter).connect(out);
        timer(function () {
          if (Math.random() > 0.5) return;
          var pop = ctx.createBufferSource();
          pop.buffer = noise("white", 0.2);
          var band = filter("bandpass", 1800, 0.8);
          var gain = ctx.createGain();
          var now = ctx.currentTime;
          gain.gain.setValueAtTime(0.0001, now);
          gain.gain.exponentialRampToValueAtTime(0.12, now + 0.006);
          gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.09);
          pop.connect(band).connect(gain).connect(out);
          pop.start(now);
          pop.stop(now + 0.12);
        }, 450, true);
      } else if (name === "forest") {
        var forestFilter = keep(filter("bandpass", 900, 0.7));
        noiseSource("brown", 0.14, sources).connect(forestFilter).connect(out);
        function chirp() {
          var w = ctx.createOscillator();
          var g = ctx.createGain();
          var now = ctx.currentTime;
          w.type = "sine";
          w.frequency.setValueAtTime(2400, now);
          w.frequency.exponentialRampToValueAtTime(3600, now + 0.08);
          w.frequency.exponentialRampToValueAtTime(2700, now + 0.17);
          g.gain.setValueAtTime(0.0001, now);
          g.gain.exponentialRampToValueAtTime(0.05, now + 0.02);
          g.gain.exponentialRampToValueAtTime(0.0001, now + 0.2);
          w.connect(g).connect(out);
          w.start(now);
          w.stop(now + 0.24);
          timer(chirp, 3500 + Math.random() * 5000, false);
        }
        timer(chirp, 2500, false);
      } else if (name === "cafe") {
        var cafeFilter = keep(filter("lowpass", 1400));
        noiseSource("pink", 0.18, sources).connect(cafeFilter).connect(out);
        out.gain.value = 0.8;
        sources.push(keep(lfo(out.gain, 0.05, 0.12)));
        function clink() {
          var w = ctx.createOscillator();
          var g = ctx.createGain();
          var now = ctx.currentTime;
          w.frequency.value = 1750 + Math.random() * 400;
          g.gain.setValueAtTime(0.0001, now);
          g.gain.exponentialRampToValueAtTime(0.03, now + 0.01);
          g.gain.exponentialRampToValueAtTime(0.0001, now + 0.12);
          w.connect(g).connect(out);
          w.start(now);
          w.stop(now + 0.14);
          timer(clink, 7000 + Math.random() * 7000, false);
        }
        timer(clink, 5000, false);
      } else if (name === "night") {
        var padFilter = keep(filter("lowpass", 800));
        [110, 164.81, 220, 329.63].forEach(function (freq) {
          var osc = ctx.createOscillator();
          var gain = ctx.createGain();
          osc.type = "sine";
          osc.frequency.value = freq;
          osc.detune.value = Math.random() * 8 - 4;
          gain.gain.value = 0.05;
          osc.connect(gain).connect(padFilter);
          osc.start(0);
          keep(osc);
          keep(gain);
        });
        padFilter.connect(out);
        out.gain.value = 0.9;
        sources.push(keep(lfo(padFilter.frequency, 0.03, 220)));
      }

      var now = ctx.currentTime;
      var targetGain = out.gain.value || 1;
      out.gain.cancelScheduledValues(now);
      out.gain.setValueAtTime(0.0001, now);
      out.gain.linearRampToValueAtTime(targetGain, now + 1.2);

      return {
        stop: function () {
          timers.forEach(function (id) {
            clearTimeout(id);
            clearInterval(id);
          });
          nodes.forEach(function (node) {
            try { node.disconnect(); } catch (e) {}
          });
          sources.forEach(function (source) {
            try { source.stop(); } catch (e) {}
          });
          try { out.disconnect(); } catch (e) {}
        }
      };
    }

    function stopCurrent() {
      if (current) {
        current.stop();
        current = null;
      }
    }

    function setVolume(value) {
      var target = Math.max(0, Math.min(100, value)) / 100 * 0.8;
      master.gain.setTargetAtTime(target, ctx.currentTime, 0.15);
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

    ctx.resume().catch(function () {});
    resumeOnGesture();

    var api = {
      set: function (name, value) {
        setVolume(value);
        if (name === currentTrack && current) {
          if (ctx.state === "suspended") ctx.resume().catch(function () {});
          return;
        }
        stopCurrent();
        currentTrack = name;
        if (name === "off") return;
        current = build(name);
        ctx.resume().catch(function () {});
        resumeOnGesture();
      }
    };
    w[key] = api;
    return api;
  }

  var controller = controllerFor(win);
  controller.set(track, volume);
})();
"""
