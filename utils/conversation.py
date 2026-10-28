# utils/conversation.py

"""把聊天记录拼成 prompt 里的一段文本。

Chat / FreeTalk / Entertainment 原来各抄了一份，只有角色名和条数不同。
"""


def format_history(
    history,
    *,
    limit: int = 10,
    assistant_label: str = "Assistant",
    user_label: str = "User",
) -> str:
    lines = []
    for message in (history or [])[-limit:]:
        role = assistant_label if message.get("role") == "assistant" else user_label
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


__all__ = ["format_history"]
