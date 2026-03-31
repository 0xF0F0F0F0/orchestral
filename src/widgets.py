"""Custom Textual widgets for Orchestral."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from .agent import Agent, AgentStatus


STATUS_BORDER_MAP = {
    AgentStatus.NEEDS_PERMISSION: "heavy",
    AgentStatus.RUNNING: "round",
    AgentStatus.COMPLETED: "double",
    AgentStatus.STOPPED: "dashed",
}

# Maps status -> theme attribute name
STATUS_THEME_KEY = {
    AgentStatus.NEEDS_PERMISSION: "secondary",  # blue-ish
    AgentStatus.RUNNING: "panel",               # muted
    AgentStatus.COMPLETED: "success",           # green
    AgentStatus.STOPPED: "surface",             # dim
}


def _theme_color(widget: Widget, key: str) -> str:
    """Resolve a theme color by attribute name."""
    theme = widget.app.current_theme
    return getattr(theme, key, None) or "#888888"


class AgentPane(Widget, can_focus=True):
    """A single agent mini-window showing status and output snippet."""

    DEFAULT_CSS = """
    AgentPane {
        height: 1fr;
        width: 1fr;
        padding: 0 1;
        border: round $panel;
    }
    AgentPane.--selected {
        background: $surface;
    }
    AgentPane .agent-title {
        height: 1;
        text-style: bold;
        color: $text;
    }
    AgentPane .agent-meta {
        height: 1;
        color: $text-muted;
    }
    AgentPane .agent-output {
        height: 1fr;
        color: $text;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        ("enter", "open_agent", "Open"),
    ]

    agent_id: reactive[str] = reactive("")
    selected: reactive[bool] = reactive(False)

    def __init__(self, agent: Agent, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent = agent
        self.agent_id = agent.id

    def compose(self) -> ComposeResult:
        yield Static(self._title_text(), classes="agent-title")
        yield Static(self._meta_text(), classes="agent-meta")
        yield Static("(waiting for output...)", classes="agent-output")

    def _title_text(self) -> str:
        a = self._agent
        branch = f" ({a.branch})" if a.branch else ""
        return f"{a.status_icon} {a.name} · {a.short_dir}{branch}"

    def _meta_text(self) -> str:
        a = self._agent
        return f"  {a.current_dir or a.working_dir}"

    def _apply_border(self) -> None:
        """Set border based on status, but override with highlight if selected."""
        if self.selected:
            color = _theme_color(self, "primary")
            self.styles.border = ("heavy", color)
        else:
            theme_key = STATUS_THEME_KEY[self._agent.status]
            color = _theme_color(self, theme_key)
            border_type = STATUS_BORDER_MAP[self._agent.status]
            self.styles.border = (border_type, color)

    def watch_selected(self, value: bool) -> None:
        if value:
            self.add_class("--selected")
        else:
            self.remove_class("--selected")
        self._apply_border()

    def update_from_agent(self, agent: Agent, snippet: str) -> None:
        self._agent = agent
        self._apply_border()

        children = list(self.children)
        if len(children) >= 3:
            children[0].update(self._title_text())
            children[1].update(self._meta_text())
            children[2].update(snippet or "(no output yet)")

    def action_open_agent(self) -> None:
        self.post_message(self.AttachRequest(self.agent_id))

    class AttachRequest(Message):
        """Posted when user presses enter on a pane."""
        def __init__(self, agent_id: str) -> None:
            super().__init__()
            self.agent_id = agent_id


class EmptySlot(Widget):
    """Placeholder for an empty agent slot."""

    DEFAULT_CSS = """
    EmptySlot {
        height: 1fr;
        width: 1fr;
        border: dashed $surface;
        content-align: center middle;
    }
    EmptySlot Static {
        text-align: center;
        color: $text-disabled;
        width: 100%;
        content-align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("(empty slot)\n\nPress [bold]n[/] to spawn agent")
