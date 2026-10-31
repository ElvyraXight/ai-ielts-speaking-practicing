# utils/ChatPage.py

"""角色聊天页的公共骨架。

猫娘 / AI闲聊 / 心理咨询 / 学业导师四个页面原来是四份约 150 行、逐行相同的
脚本：开场白、播放器、记忆侧栏、发送按钮全抄了一遍。
任何一个小修（比如空音频文件）都要改四处，总有漏掉的一份。

这里把流程收成一份，页面只剩"人设 + 几个文案"。每个页面用 `prefix` 区分
session_state 的键（cat / friend / psy / mentor），所以四个角色的对话状态
互不干扰，老会话升级后也还在。

布局和「Personal tutor」一致：标题在页首、消息直接在页面里往下排、
输入框固定在页底；不套固定高度的滚动盒子，不提供语音输入，也不做
消息编辑（改一句话请重新发）。
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import streamlit as st

from utils.ChatHistory import load as load_chat_history
from utils.ChatHistory import load_meta as load_chat_meta
from utils.ChatHistory import render_restart_button, save as save_chat_history
from utils.ChatHistory import update_meta as update_chat_meta
from utils.config import describe_llm
from utils.Entertainment import get_entertainment_answer
from utils.LongNotes import render_sticky_note_form
from utils.Memory import render_memory_sidebar
from utils.Notes import delete_note, note_ready, render_notes_sidebar
from utils.tts import existing_audio


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
    caption: str = ""
    note_kind: str | None = None
    note_expander: str = ""
    # 中文回复方式：True=先理解再用中文重新说一遍（默认，所有角色页）；
    # False=逐句翻译英文。四个角色现在统一走 True。
    rewrite_zh: bool = True
    sidebar: Callable[[], None] | None = None
    sidebar_top: Callable[[], None] | None = None  # 侧栏最上面（搜索框下面）


def _ensure_state(key: str, value) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


def render_chat_page(spec: ChatPageSpec) -> None:
    """渲染一个角色聊天页；页面文件只负责提供人设和文案。"""
    st.set_page_config(page_title=spec.page_title, page_icon=spec.page_icon, layout="wide")

    with st.sidebar:
        if spec.sidebar_top:
            spec.sidebar_top()
        render_sticky_note_form(f"{spec.prefix}_sticky")

    if spec.sidebar:
        with st.sidebar:
            spec.sidebar()
    if spec.memory_key:
        render_memory_sidebar(spec.memory_key)

    messages_key = f"{spec.prefix}_messages"
    buffer_key = f"{spec.prefix}_input_buffer"
    reset_buffer_key = f"{spec.prefix}_reset_buffer"
    if st.session_state.pop(reset_buffer_key, False):
        st.session_state[buffer_key] = ""
    session_id_key = f"{spec.prefix}_session_id"
    session_date_key = f"{spec.prefix}_session_date"
    history_key = {"cat": "catgirl", "psy": "psychologist"}.get(
        spec.prefix, spec.prefix
    )

    if messages_key not in st.session_state:
        st.session_state[messages_key] = load_chat_history(history_key)

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
        update_chat_meta(
            history_key,
            {
                "session_id": st.session_state[session_id_key],
                "session_date": st.session_state[session_date_key],
            },
        )
        # 当前这次对话的笔记结束前不显示；重开聊天后才出现在历史里。
        render_notes_sidebar(
            spec.note_kind,
            spec.note_expander,
            exclude_id=st.session_state[session_id_key],
        )

    def send_message(user_input: str = "") -> None:
        user_input = str(
            user_input or st.session_state.get(buffer_key, "")
        ).strip()
        if not user_input:
            return

        st.session_state[messages_key].append({"role": "user", "content": user_input})
        save_chat_history(history_key, st.session_state[messages_key])

        with st.spinner(spec.spinner_send):
            # 笔记按「结束日期」记：每次写入用当前日期，最后一次更新就是这次会话的结束日期。
            note_date = datetime.now().strftime("%Y-%m-%d")
            if spec.note_kind and st.session_state.get(session_date_key) != note_date:
                st.session_state[session_date_key] = note_date
                update_chat_meta(
                    history_key,
                    {
                        "session_id": st.session_state[session_id_key],
                        "session_date": note_date,
                    },
                )
            bot_data, audio_file = get_entertainment_answer(
                user_input,
                st.session_state[messages_key],
                spec.persona,
                memory_key=spec.memory_key,
                memory_label=spec.memory_label,
                note_kind=spec.note_kind,
                note_id=st.session_state.get(session_id_key),
                note_date=note_date,
                voice=spec.voice,
                rewrite_zh=spec.rewrite_zh,
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
        if spec.note_kind:
            # 3 条以内（不到第 4 次往来）的会话不保留笔记。旧版本 / 中途改规则
            # 可能已经给它写过一条，这里真删掉，而不是只不显示。
            current = st.session_state.get(messages_key) or []
            if not note_ready(current):
                delete_note(
                    spec.note_kind,
                    st.session_state.get(session_id_key),
                )
        st.session_state.pop(messages_key, None)
        st.session_state[reset_buffer_key] = True
        if spec.note_kind:
            st.session_state[session_id_key] = uuid.uuid4().hex[:12]
            st.session_state[session_date_key] = datetime.now().strftime("%Y-%m-%d")
            update_chat_meta(
                history_key,
                {
                    "session_id": st.session_state[session_id_key],
                    "session_date": st.session_state[session_date_key],
                },
            )

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
                intro_fallback=spec.intro_fallback,
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

    for message in st.session_state[messages_key]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            audio = existing_audio(message.get("audio"))
            if audio:
                st.audio(audio)

    if prompt := st.chat_input(
        "输入你想说的话…",
        key=buffer_key,
    ):
        send_message(prompt)
        st.rerun()

    restart_message = f"确认清空「{spec.page_title}」的聊天记录？"
    if spec.note_kind and not note_ready(st.session_state[messages_key]):
        record_label = (
            "诊疗笔记" if spec.note_kind == "psychologist" else "指导记录"
        )
        restart_message += (
            f"\n\n这次对话 3 条以内，重新开始后不会保存{record_label}。"
        )
    render_restart_button(
        history_key,
        restart_chat,
        message=restart_message,
    )


__all__ = ["ChatPageSpec", "render_chat_page"]
