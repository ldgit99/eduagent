"""The local browser interface (``edu-agent run --web``)."""

from edu_agent.web.assets import render_page
from edu_agent.web.server import ChatServer, ChatSession

__all__ = ["ChatServer", "ChatSession", "render_page"]
