"""The single page ``edu-agent run --web`` serves.

The markup lives in ``templates/web/index.html.j2``, not in a Python string. It
used to be a ``str.format`` template, which meant every brace in the CSS and the
JavaScript had to be doubled — 166 lines that no editor would highlight and no
linter would read. As a template it is just the page.

It is still one self-contained file: inline CSS and JS, no build step, no network
fetch. A student can open it and read the whole interface.
"""

from __future__ import annotations

from edu_agent.documents.render import render_template

STRINGS = {
    "ko": {
        "reset_label": "새 대화",
        "send_label": "보내기",
        "placeholder": "여기에 쓰세요. Enter 로 보내고, Shift+Enter 로 줄을 바꿉니다.",
        "hint": "대화는 이 컴퓨터에만 저장됩니다. 창을 닫으면 터미널에서 Ctrl+C 로 끝내세요.",
        "privacy": "이 대화는 학습 기록으로 이 컴퓨터에 저장됩니다. 이름·연락처 같은 개인정보는 적지 마세요.",
        "tutor_label": "튜터",
        "learner_label": "나",
        "error_text": "응답을 가져오지 못했습니다.",
    },
    "en": {
        "reset_label": "New chat",
        "send_label": "Send",
        "placeholder": "Type here. Enter sends, Shift+Enter adds a line.",
        "hint": "This conversation is stored on this computer only. Close with Ctrl+C in the terminal.",
        "privacy": "This conversation is saved on this computer as a learning record. Do not type personal information.",
        "tutor_label": "Tutor",
        "learner_label": "You",
        "error_text": "Could not get a response.",
    },
}


def render_page(*, title: str, role: str, lang: str = "ko") -> str:
    strings = STRINGS.get(lang, STRINGS["ko"])
    return render_template(
        "web/index.html.j2", lang=lang, title=_escape(title), role=_escape(role), **strings
    )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


__all__ = ["STRINGS", "render_page"]
