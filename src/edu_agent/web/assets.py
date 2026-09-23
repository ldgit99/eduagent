"""The single page ``edu-agent run --web`` serves.

Kept as one string with inline CSS and JS on purpose: a student can open it in a
browser with no build step, no network fetch and no node_modules, and the whole
interface is one file they can read.
"""

from __future__ import annotations

PAGE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  color-scheme: light dark;
  --bg: #ffffff; --fg: #16181d; --muted: #6b7280; --line: #e5e7eb;
  --tutor-bg: #eef2ff; --learner-bg: #f3f4f6; --accent: #4f46e5;
  --warn-bg: #fef3c7; --warn-fg: #92400e; --tool-bg: #ecfdf5; --tool-fg: #065f46;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0f1115; --fg: #e7e9ee; --muted: #9aa1ad; --line: #262a33;
    --tutor-bg: #1c2233; --learner-bg: #191c23; --accent: #818cf8;
    --warn-bg: #3a2d10; --warn-fg: #fcd34d; --tool-bg: #10241c; --tool-fg: #6ee7b7;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.6 system-ui, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
  display: flex; flex-direction: column; height: 100dvh;
}}
header {{
  padding: 14px 16px; border-bottom: 1px solid var(--line);
  display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
}}
header h1 {{ font-size: 16px; margin: 0; }}
header .role {{ color: var(--muted); font-size: 13px; }}
header .spacer {{ flex: 1; }}
header button {{
  background: none; border: 1px solid var(--line); color: var(--muted);
  border-radius: 6px; padding: 4px 10px; font-size: 13px; cursor: pointer;
}}
header button:hover {{ color: var(--fg); }}
#log {{ flex: 1; overflow-y: auto; padding: 16px; }}
.wrap {{ max-width: 760px; margin: 0 auto; }}
.msg {{ margin-bottom: 14px; }}
.who {{ font-size: 12px; color: var(--muted); margin-bottom: 4px; }}
.bubble {{
  padding: 10px 13px; border-radius: 10px; white-space: pre-wrap; word-break: break-word;
}}
.learner .bubble {{ background: var(--learner-bg); }}
.tutor .bubble {{ background: var(--tutor-bg); }}
.note {{
  font-size: 12px; margin-top: 6px; padding: 6px 10px; border-radius: 6px;
  background: var(--warn-bg); color: var(--warn-fg);
}}
.note.tool {{ background: var(--tool-bg); color: var(--tool-fg); }}
.privacy {{ color: var(--muted); font-size: 12px; margin-bottom: 16px; }}
form {{ border-top: 1px solid var(--line); padding: 12px 16px; }}
form .wrap {{ display: flex; gap: 8px; }}
textarea {{
  flex: 1; resize: none; border: 1px solid var(--line); border-radius: 8px;
  padding: 10px; font: inherit; background: var(--bg); color: var(--fg); min-height: 44px;
}}
button.send {{
  background: var(--accent); color: #fff; border: 0; border-radius: 8px;
  padding: 0 18px; font: inherit; cursor: pointer;
}}
button.send:disabled {{ opacity: .5; cursor: default; }}
.hint {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <span class="role">{role}</span>
  <span class="spacer"></span>
  <button id="reset">{reset_label}</button>
</header>

<div id="log"><div class="wrap">
  <p class="privacy">{privacy}</p>
</div></div>

<form id="composer">
  <div class="wrap">
    <textarea id="input" placeholder="{placeholder}" autofocus></textarea>
    <button class="send" type="submit">{send_label}</button>
  </div>
  <div class="wrap"><p class="hint">{hint}</p></div>
</form>

<script>
const TOKEN = new URLSearchParams(location.search).get("k") || "";
const log = document.querySelector("#log .wrap");
const input = document.getElementById("input");
const form = document.getElementById("composer");
const sendButton = form.querySelector("button.send");

function bubble(who, role, text) {{
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;
  const label = document.createElement("div");
  label.className = "who";
  label.textContent = who;
  const body = document.createElement("div");
  body.className = "bubble";
  body.textContent = text;
  wrap.append(label, body);
  log.appendChild(wrap);
  log.parentElement.scrollTop = log.parentElement.scrollHeight;
  return wrap;
}}

function note(parent, text, kind) {{
  const el = document.createElement("div");
  el.className = "note" + (kind ? " " + kind : "");
  el.textContent = text;
  parent.appendChild(el);
}}

async function api(path, body) {{
  const response = await fetch(path, {{
    method: "POST",
    headers: {{ "Content-Type": "application/json", "X-Edu-Token": TOKEN }},
    body: JSON.stringify(body || {{}}),
  }});
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}}

function render(turn) {{
  const el = bubble("{tutor_label}", "tutor", turn.message);
  (turn.tools || []).forEach(tool => note(el, tool, "tool"));
  (turn.notes || []).forEach(text => note(el, text));
}}

form.addEventListener("submit", async event => {{
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;
  bubble("{learner_label}", "learner", message);
  input.value = "";
  sendButton.disabled = true;
  try {{
    render(await api("/api/turn", {{ message }}));
  }} catch (error) {{
    const el = bubble("{tutor_label}", "tutor", "{error_text}");
    note(el, String(error));
  }} finally {{
    sendButton.disabled = false;
    input.focus();
  }}
}});

input.addEventListener("keydown", event => {{
  if (event.key === "Enter" && !event.shiftKey) {{
    event.preventDefault();
    form.requestSubmit();
  }}
}});

document.getElementById("reset").addEventListener("click", async () => {{
  await api("/api/reset");
  log.innerHTML = '<p class="privacy">{privacy}</p>';
  input.focus();
}});
</script>
</body>
</html>
"""

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
    return PAGE.format(lang=lang, title=_escape(title), role=_escape(role), **strings)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


__all__ = ["render_page"]
