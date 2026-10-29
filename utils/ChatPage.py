# utils/ChatPage.py

"""角色聊天页的公共骨架。

猫娘 / AI闲聊 / 心理咨询 / 学业导师四个页面原来是四份约 150 行、逐行相同的
脚本：录音去重、编辑重发、开场白、播放器、记忆侧栏、发送按钮全抄了一遍。
任何一个小修（比如空音频文件）都要改四处，总有漏掉的一份。

这里把流程收成一份，页面只剩"人设 + 几个文案"。每个页面用 `prefix` 区分
session_state 的键（cat / friend / psy / mentor），所以四个角色的对话和
编辑状态互不干扰，老会话升级后也还在。
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import streamlit as st

from utils.asr import transcribe_upload
from utils.ChatHistory import load as load_chat_history
from utils.ChatHistory import load_meta as load_chat_meta
from utils.ChatHistory import render_restart_button, save as save_chat_history
from utils.ChatHistory import save_meta as save_chat_meta
from utils.config import describe_llm
from utils.Entertainment import get_entertainment_answer
from utils.LongNotes import render_sticky_note_form
from utils.Memory import render_memory_sidebar
from utils.Notes import render_notes_sidebar
from utils.tts import existing_audio

_AUDIO_INPUT_HELP = "需要允许浏览器麦克风权限；若持续报错，请改用文字输入。"


@dataclass(frozen=True)
class ChatPageSpec:
    """一个角色聊天页需要的全部差异项。"""

    prefix: str                 # session_state 键前缀，也是按钮 key 的来源
    page_title: str
    page_icon: str
    heading: str
    persona: str
    voice: str
    memory_key: str
    memory_label: str
    intro_fallback: str
    spinner_intro: str
    spinner_send: str
    spinner_listen: str = "正在听..."
    caption: str = ""
    note_kind: str | None = None
    note_expander: str = ""
    sidebar: Callable[[], None] | None = None


def _ensure_state(key: str, value) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


def render_chat_page(spec: ChatPageSpec) -> None:
    """渲染一个角色聊天页；页面文件只负责提供人设和文案。"""
    st.set_page_config(page_title=spec.page_title, page_icon=spec.page_icon, layout="wide")

    with st.sidebar:
        render_sticky_note_form(f"{spec.prefix}_sticky")

    if spec.sidebar:
        with st.sidebar:
            spec.sidebar()
    if spec.memory_key:
        render_memory_sidebar(spec.memory_key)
    if spec.note_kind:
        render_notes_sidebar(spec.note_kind, spec.note_expander)

    messages_key = f"{spec.prefix}_messages"
    edit_mode_key = f"{spec.prefix}_edit_mode"
    edit_index_key = f"{spec.prefix}_edit_index"
    buffer_key = f"{spec.prefix}_input_buffer"
    session_id_key = f"{spec.prefix}_session_id"
    session_date_key = f"{spec.prefix}_session_date"
    history_key = {"cat": "catgirl", "psy": "psychologist"}.get(
        spec.prefix, spec.prefix
    )

    if messages_key not in st.session_state:
        st.session_state[messages_key] = load_chat_history(history_key)

    _ensure_state(edit_mode_key, False)
    _ensure_state(edit_index_key, -1)
    _ensure_state(buffer_key, "")
    if spec.note_kind:
        # 一次浏览器会话 = 一份诊疗笔记 / 指导记录；刷新后沿用同一份。
        saved_meta = load_chat_meta(history_key)
        _ensure_state(
            session_id_key,
            saved_meta.get("session_id") or uuid.uuid4().hex[:12],
        )
        _ensure_state(
            session_date_key,
            saved_meta.get("session_date") or datetime.now().strftime("%Y-%m-%d"),
        )
        save_chat_meta(
            history_key,
            {
                "session_id": st.session_state[session_id_key],
                "session_date": st.session_state[session_date_key],
            },
        )

    def send_message() -> None:
        user_input = str(st.session_state[buffer_key] or "").strip()
        if not user_input:
            return
        st.session_state[buffer_key] = ""

        if st.session_state[edit_mode_key]:
            st.session_state[messages_key] = st.session_state[messages_key][
                : st.session_state[edit_index_key]
            ]
            st.session_state[edit_mode_key] = False

        st.session_state[messages_key].append({"role": "user", "content": user_input})
        save_chat_history(history_key, st.session_state[messages_key])

        with st.spinner(spec.spinner_send):
            bot_data, audio_file = get_entertainment_answer(
                user_input,
                st.session_state[messages_key],
                spec.persona,
                memory_key=spec.memory_key,
                memory_label=spec.memory_label,
                note_kind=spec.note_kind,
                note_id=st.session_state.get(session_id_key),
                note_date=st.session_state.get(session_date_key),
                voice=spec.voice,
            )

        st.session_state[messages_key].append(
            {
                "role": "assistant",
                "content": bot_data.get("reply", ""),
                "audio": audio_file,
                "correction": bot_data.get("correction", ""),
                "suggestion": bot_data.get("suggestion", ""),
                "model_answer": bot_data.get("model_answer", ""),
            }
        )
        save_chat_history(history_key, st.session_state[messages_key])

    def restart_chat() -> None:
        st.session_state.pop(messages_key, None)
        st.session_state[edit_mode_key] = False
        st.session_state[edit_index_key] = -1
        st.session_state[buffer_key] = ""
        if spec.note_kind:
            st.session_state[session_id_key] = uuid.uuid4().hex[:12]
            st.session_state[session_date_key] = datetime.now().strftime("%Y-%m-%d")
            save_chat_meta(
                history_key,
                {
                    "session_id": st.session_state[session_id_key],
                    "session_date": st.session_state[session_date_key],
                },
            )

    with st.container(height=600):
        st.title(spec.heading)
        if spec.caption:
            st.caption(spec.caption)
        st.caption(f"🤖 当前模型：{describe_llm()}")

        if not st.session_state[messages_key]:
            with st.spinner(spec.spinner_intro):
                intro_data, intro_audio = get_entertainment_answer(
                    "",
                    [],
                    spec.persona,
                    memory_key=spec.memory_key,
                    memory_label=spec.memory_label,
                    voice=spec.voice,
                )
            st.session_state[messages_key] = [
                {
                    "role": "assistant",
                    "content": intro_data.get("reply", spec.intro_fallback),
                    "audio": intro_audio,
                    "correction": "",
                    "suggestion": "",
                    "model_answer": "",
                }
            ]
            save_chat_history(history_key, st.session_state[messages_key])

        for index, message in enumerate(st.session_state[messages_key]):
            with st.chat_message(message["role"]):
                col1, col2 = st.columns([9, 1])
                with col1:
                    st.write(message["content"])
                    audio = existing_audio(message.get("audio"))
                    if audio:
                        st.audio(audio)
                with col2:
                    if message["role"] == "user" and st.button(
                        "✏️", key=f"{spec.prefix}_edit_{index}", help="修改这句话"
                    ):
                        st.session_state[edit_mode_key] = True
                        st.session_state[edit_index_key] = index
                        st.session_state[buffer_key] = message["content"]
                        st.rerun()

    recorded = st.audio_input(
        "🎤 点击麦克风说话", key=f"{spec.prefix}_audio", help=_AUDIO_INPUT_HELP
    )
    if recorded:
        audio_id = hashlib.md5(recorded.getvalue()).hexdigest()
        seen_key = f"{spec.prefix}_last_audio_id"
        _ensure_state(seen_key, None)
        if audio_id != st.session_state[seen_key]:
            st.session_state[seen_key] = audio_id
            with st.spinner(spec.spinner_listen):
                user_text = transcribe_upload(recorded)
            if user_text and user_text.strip():
                st.session_state[buffer_key] = user_text
                st.toast("🎧 已转成文字，确认后点发送")
                st.rerun()
            else:
                st.toast("🎧 没有识别出内容，请再说一次或改用文字输入")

    st.caption("语音会先转成文字，确认后再点发送。")

    with st.container():
        st.text_area(
            "输入你想说的话:",
            key=buffer_key,
            height=80,
            label_visibility="collapsed",
        )
        st.button(
            "发送 🚀",
            key=f"send_{spec.prefix}",
            on_click=send_message,
            shortcut="Ctrl+Enter",
            use_container_width=True,
            type="primary",
        )

    render_restart_button(history_key, restart_chat)


__all__ = ["ChatPageSpec", "render_chat_page"]
