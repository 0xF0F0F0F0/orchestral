"""Agent lifecycle management and state tracking."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import tmux


# Box-drawing and decorative unicode ranges used by Claude Code's TUI
_BOX_CHARS = set("─━│┃┄┅┆┇┈┉┊┋┌┍┎┏┐┑┒┓└┕┖┗┘┙┚┛├┝┞┟┠┡┢┣┤┥┦┧┨┩┪┫┬┭┮┯┰┱┲┳┴┵┶┷┸┹┺┻┼┽┾┿╀╁╂╃╄╅╆╇╈╉╊╋╌╍╎╏═║╒╓╔╕╖╗╘╙╚╛╜╝╞╟╠╡╢╣╤╥╦╧╨╩╪╫╬╭╮╯╰╱╲╳")


def _is_decoration_line(line: str) -> bool:
    """Check if a line is purely box-drawing / decorative characters."""
    stripped = line.strip()
    if not stripped:
        return True
    non_space = stripped.replace(" ", "")
    if not non_space:
        return True
    box_count = sum(1 for c in non_space if c in _BOX_CHARS)
    # Only strip lines that are almost entirely decoration (>80%)
    # to avoid eating legitimate output from non-Claude-Code tools
    return box_count / len(non_space) > 0.8


def _clean_line(line: str) -> str:
    """Remove box-drawing chars and collapse whitespace."""
    cleaned = "".join(" " if c in _BOX_CHARS else c for c in line)
    # Collapse multiple spaces
    cleaned = re.sub(r"  +", "  ", cleaned).strip()
    return cleaned


def clean_snippet(raw: str, max_lines: int = 8, theme=None) -> str:
    """Clean tmux capture output into readable snippet with Rich markup."""
    lines = raw.splitlines()

    cleaned = []
    for line in lines:
        if _is_decoration_line(line):
            continue
        cl = _clean_line(line)
        if not cl:
            continue
        cleaned.append(cl)

    # Take last N lines
    snippet_lines = cleaned[-max_lines:] if cleaned else []

    # Resolve theme colors
    colors = _theme_colors(theme)

    colored = []
    for line in snippet_lines:
        colored.append(_colorize(line, colors))

    return "\n".join(colored) if colored else "(no output yet)"


def _theme_colors(theme) -> dict:
    """Extract color palette from theme, with fallbacks."""
    if theme is None:
        return {
            "secondary": "#7AA2F7",
            "error": "#F7768E",
            "warning": "#E0AF68",
            "success": "#9ECE6A",
            "primary": "#BB9AF7",
            "accent": "#FF9E64",
            "foreground": "#a9b1d6",
            "panel": "#414868",
        }
    return {
        "secondary": theme.secondary or "#7AA2F7",
        "error": theme.error or "#F7768E",
        "warning": theme.warning or "#E0AF68",
        "success": theme.success or "#9ECE6A",
        "primary": theme.primary or "#BB9AF7",
        "accent": theme.accent or "#FF9E64",
        "foreground": theme.foreground or "#a9b1d6",
        "panel": theme.panel or "#414868",
    }


def _colorize(line: str, c: dict) -> str:
    """Apply Rich markup based on content patterns, using theme colors."""
    low = line.lower()

    # User prompts (❯ or > at start, $ prompt)
    if line.lstrip().startswith(("❯", ">", "❯", "$")):
        return f"[bold {c['secondary']}]{_escape(line)}[/]"

    # Errors
    if any(w in low for w in ("error", "failed", "traceback", "exception", "fatal")):
        return f"[bold {c['error']}]{_escape(line)}[/]"

    # Warnings
    if any(w in low for w in ("warning", "warn", "deprecated")):
        return f"[{c['warning']}]{_escape(line)}[/]"

    # Success / completion
    if any(w in low for w in ("success", "completed", "done", "passed", "✓", "✔", "approved")):
        return f"[{c['success']}]{_escape(line)}[/]"

    # Tool calls — Claude Code style
    if any(w in line for w in ("Read(", "Write(", "Edit(", "Bash(", "Glob(", "Grep(")):
        return f"[bold {c['primary']}]{_escape(line)}[/]"

    # Tool calls — Codex style (function_call, tool output markers)
    if any(w in line for w in ("function_call", "tool_output", ">>> ", "codex ", "Codex ")):
        return f"[bold {c['primary']}]{_escape(line)}[/]"

    # File operations (generic)
    if any(w in line for w in ("Read ", "Write ", "Edit ", "Bash ", "created", "modified", "updated")):
        return f"[{c['accent']}]{_escape(line)}[/]"

    # File paths (common in tool output)
    if re.match(r"^\s*[/~][\w/.\-]+", line):
        return f"[{c['accent']}]{_escape(line)}[/]"

    # Permission / confirmation prompts (generic)
    if any(w in line for w in ("Allow", "approve", "Enter to confirm", "Yes, I trust",
                                "confirm", "Confirm", "accept", "Accept")):
        return f"[bold {c['secondary']}]{_escape(line)}[/]"

    # Dimmed noise
    if any(w in low for w in ("? for shortcuts", "ctrl+", "press enter", "loading", "thinking")):
        return f"[{c['panel']}]{_escape(line)}[/]"

    # Default
    return f"[{c['foreground']}]{_escape(line)}[/]"


def _escape(text: str) -> str:
    """Escape Rich markup characters in text."""
    return text.replace("[", "\\[").replace("]", "\\]")


class AgentStatus(Enum):
    RUNNING = "running"
    NEEDS_PERMISSION = "needs_permission"
    COMPLETED = "completed"
    STOPPED = "stopped"


@dataclass
class Agent:
    id: str
    name: str
    working_dir: str
    command: str
    status: AgentStatus = AgentStatus.RUNNING
    created_at: float = field(default_factory=time.time)
    last_output: str = ""
    repo_name: str = ""
    branch: str = ""
    current_dir: str = ""

    @property
    def status_icon(self) -> str:
        return {
            AgentStatus.NEEDS_PERMISSION: "⏳",
            AgentStatus.RUNNING: "⚙",
            AgentStatus.COMPLETED: "✓",
            AgentStatus.STOPPED: "■",
        }[self.status]

    @property
    def title_line(self) -> str:
        """e.g. 'nvim-settings (main)' or just the folder name."""
        repo = self.repo_name or Path(self.current_dir or self.working_dir).name
        if self.branch:
            return f"{repo} ({self.branch})"
        return repo

    @property
    def short_dir(self) -> str:
        return Path(self.current_dir or self.working_dir).name


# Patterns that indicate human intervention is required (blue border)
NEEDS_HUMAN_PATTERNS = [
    # Claude Code specific
    "Enter to confirm",
    "Allow once",
    "Allow always",
    "Esc to cancel",
    "I trust this folder",
    "Do you want to allow",
    "wants to execute",
    "wants to read",
    "wants to write",
    "wants to edit",
    "? for shortcuts",  # idle at prompt, waiting for user input
    # Codex specific
    "approve",
    "Approve",
    "sandbox",
    "confirm execution",
    # Generic
    "Allow ",
    "Approve?",
    "(y/n)",
    "[Y/n]",
    "[y/N]",
    "Press Enter to",
    "Continue?",
    "Proceed?",
    "Yes / No",
    "accept",
    "Accept",
    "(yes/no)",
]

# Regex: idle prompt line — just ❯ or $ (possibly with spaces) and nothing else
_IDLE_PROMPT_RE = re.compile(r"^\s*[❯$>]\s*$")

# Completion patterns
COMPLETION_PATTERNS = [
    "Task completed",
    "All done",
    "Finished",
]

# Regex for lines that are clearly just a shell prompt (agent exited)
SHELL_PROMPT_RE = re.compile(r"^[\w@\-\.]+[:\$#%>]\s*$")


class AgentManager:
    def __init__(self) -> None:
        self.agents: dict[str, Agent] = {}
        self._next_id = 1

    def spawn(self, name: str, working_dir: str, command: str) -> Agent | None:
        if len(self.agents) >= 6:
            return None

        agent_id = f"a{self._next_id}"
        self._next_id += 1

        agent = Agent(
            id=agent_id,
            name=name,
            working_dir=working_dir,
            command=command,
        )

        if not tmux.create_session(agent_id, working_dir, command):
            return None

        self.agents[agent_id] = agent
        return agent

    def remove(self, agent_id: str) -> bool:
        if agent_id not in self.agents:
            return False
        tmux.kill_session(agent_id)
        del self.agents[agent_id]
        return True

    def refresh_all(self) -> None:
        """Poll tmux panes and update agent statuses."""
        for agent_id, agent in list(self.agents.items()):
            if agent.status == AgentStatus.STOPPED:
                continue

            if not tmux.session_exists(agent_id):
                agent.status = AgentStatus.COMPLETED
                continue

            # Capture output
            output = tmux.capture_pane(agent_id, lines=40)
            agent.last_output = output

            # Update cwd / repo / branch
            cwd = tmux.get_pane_cwd(agent_id)
            if cwd:
                agent.current_dir = cwd
                repo = tmux.get_git_repo_name(cwd)
                if repo:
                    agent.repo_name = repo
                branch = tmux.get_git_branch(cwd)
                if branch:
                    agent.branch = branch

            # Check last visible lines (skip blanks) for status signals
            visible_lines = [l for l in output.splitlines() if l.strip()] if output else []
            recent = "\n".join(visible_lines[-12:])

            # Check for idle prompt (just ❯ alone)
            has_idle_prompt = any(_IDLE_PROMPT_RE.match(l) for l in visible_lines[-4:])

            if has_idle_prompt or any(p in recent for p in NEEDS_HUMAN_PATTERNS):
                agent.status = AgentStatus.NEEDS_PERMISSION
            elif any(p in recent for p in COMPLETION_PATTERNS):
                agent.status = AgentStatus.COMPLETED
            else:
                agent.status = AgentStatus.RUNNING

    def get_snippet(self, agent_id: str, lines: int = 8, theme=None) -> str:
        """Get a cleaned, colorized snippet of recent output for overview."""
        agent = self.agents.get(agent_id)
        if not agent or not agent.last_output:
            return "(no output yet)"
        return clean_snippet(agent.last_output, max_lines=lines, theme=theme)

    def sync_from_tmux(self) -> None:
        """Discover any orphaned orchestral sessions from previous runs."""
        live_ids = tmux.list_orchestral_sessions()
        for aid in live_ids:
            if aid not in self.agents:
                self.agents[aid] = Agent(
                    id=aid,
                    name=f"recovered-{aid}",
                    working_dir="~",
                    command="(recovered session)",
                    status=AgentStatus.RUNNING,
                )
                # Parse next ID
                try:
                    num = int(aid.removeprefix("a"))
                    if num >= self._next_id:
                        self._next_id = num + 1
                except ValueError:
                    pass
