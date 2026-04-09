"""Orchestral - AI Agent Orchestra TUI."""

import json
import os
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".config" / "orchestral"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def _save_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import (
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    Static,
    Button,
)

from .agent import AgentManager, AgentStatus
from .tmux import ensure_tmux
from .widgets import AgentPane, EmptySlot

import subprocess as _subprocess


# ── Spawn Dialog ────────────────────────────────────────────────


class _FilteredTree(DirectoryTree):
    """DirectoryTree that hides dotfiles/dirs."""

    def filter_paths(self, paths):
        return [p for p in paths if not p.name.startswith(".")]


class SpawnDialog(ModalScreen[Optional[dict]]):
    """Spawn dialog with neotree-style directory browser."""

    DEFAULT_CSS = """
    SpawnDialog {
        align: center middle;
    }
    SpawnDialog > Vertical {
        width: 80;
        height: 30;
        border: heavy $primary;
        background: $surface;
        padding: 1 2;
    }
    SpawnDialog .field-label {
        margin-top: 1;
        margin-bottom: 0;
        color: $text-muted;
    }
    SpawnDialog Input {
        margin-bottom: 0;
    }
    SpawnDialog #selected-path {
        height: 1;
        color: $text;
        margin-top: 0;
        padding: 0 1;
    }
    SpawnDialog .dialog-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    SpawnDialog .dialog-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Spawn", show=False),
    ]

    def __init__(self, start_dir: str = "~") -> None:
        super().__init__()
        self._start_dir = str(Path(start_dir).expanduser())

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[bold]spawn agent[/]")
            yield Label("name", classes="field-label")
            yield Input(placeholder="my-agent", id="agent-name")
            yield Label("command", classes="field-label")
            yield Input(value="claude", id="agent-cmd")
            yield Label("directory", classes="field-label")
            yield _FilteredTree(self._start_dir, id="dir-tree")
            yield Static(f"[bold]{self._start_dir}[/]", id="selected-path")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Spawn (ctrl+s)", variant="primary", id="btn-spawn")
                yield Button("Cancel (esc)", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#agent-name", Input).focus()
        self._selected_dir = self._start_dir

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        """User selected a directory in the tree."""
        self._selected_dir = str(event.path)
        self.query_one("#selected-path", Static).update(f"[bold]{self._selected_dir}[/]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-spawn":
            self._do_submit()
        else:
            self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            focused = self.focused
            cycle = ["agent-name", "agent-cmd", "dir-tree", "btn-spawn"]
            if focused is not None and hasattr(focused, "id") and focused.id in cycle:
                idx = (cycle.index(focused.id) + 1) % len(cycle)
                self.query_one(f"#{cycle[idx]}").focus()
            else:
                self.query_one("#agent-name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._do_submit()

    def _do_submit(self) -> None:
        name = self.query_one("#agent-name", Input).value.strip() or "agent"
        cmd = self.query_one("#agent-cmd", Input).value.strip() or "claude"
        directory = self._selected_dir

        if not Path(directory).is_dir():
            self.notify(f"Not a directory: {directory}", severity="error")
            return

        self.dismiss({"name": name, "command": cmd, "dir": directory})

    def action_submit(self) -> None:
        self._do_submit()

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── Confirm Delete Dialog ───────────────────────────────────────


class ConfirmDeleteDialog(ModalScreen[bool]):
    """Simple y/n confirmation to delete an agent."""

    DEFAULT_CSS = """
    ConfirmDeleteDialog {
        align: center middle;
    }
    ConfirmDeleteDialog > Vertical {
        width: 45;
        height: auto;
        background: $surface;
        padding: 1 2;
    }
    ConfirmDeleteDialog .dialog-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    ConfirmDeleteDialog Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "cancel", "No", show=False),
    ]

    def __init__(self, agent_name: str) -> None:
        super().__init__()
        self._agent_name = agent_name

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"Delete [bold]{self._agent_name}[/]?")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Yes (y)", variant="default", id="btn-yes")
                yield Button("No (n)", variant="default", id="btn-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


# ── Main App ────────────────────────────────────────────────────


class OrcApp(App):
    """Orchestral - manage and observe your AI agent orchestra."""

    TITLE = "orchestral"
    SUB_TITLE = ""

    CSS = """
    Screen {
        background: $surface-darken-1;
    }
    #agent-grid {
        grid-size: 3 2;
        grid-gutter: 1;
        padding: 1;
        height: 1fr;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text;
        padding: 0 2;
    }
    """

    BINDINGS = [
        Binding("n", "spawn_agent", "New Agent"),
        Binding("d", "delete_agent", "Delete Agent"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        cfg = _load_config()
        self.theme = cfg.get("theme", "tokyo-night")
        self.manager = AgentManager()
        self._selected_idx: int = 0

    def watch_theme(self, old_value: str, new_value: str) -> None:
        """Persist theme choice when user changes it."""
        cfg = _load_config()
        cfg["theme"] = new_value
        _save_config(cfg)

    def _get_panes(self) -> list[AgentPane]:
        grid = self.query_one("#agent-grid", Grid)
        return [c for c in grid.children if isinstance(c, AgentPane)]

    def _get_all_slots(self) -> list:
        grid = self.query_one("#agent-grid", Grid)
        return list(grid.children)

    def _sync_selection(self) -> None:
        """Apply the selected highlight to exactly one slot and ensure focus."""
        slots = self._get_all_slots()
        if not slots:
            return
        self._selected_idx = max(0, min(self._selected_idx, len(slots) - 1))
        for i, slot in enumerate(slots):
            if isinstance(slot, AgentPane):
                slot.selected = (i == self._selected_idx)
            elif isinstance(slot, EmptySlot):
                theme = self.current_theme
                if i == self._selected_idx:
                    slot.styles.border = ("heavy", theme.primary or "#888888")
                else:
                    slot.styles.border = ("dashed", theme.surface or "#333333")
        # Keep the app itself focused so on_key always fires
        self.screen.set_focus(None)

    def _nav(self, direction: str) -> None:
        slots = self._get_all_slots()
        if not slots:
            return
        total = len(slots)
        cols = 3
        idx = self._selected_idx
        if direction == "left":
            if idx % cols > 0:
                idx -= 1
        elif direction == "right":
            if idx % cols < cols - 1 and idx + 1 < total:
                idx += 1
        elif direction == "up":
            if idx >= cols:
                idx -= cols
        elif direction == "down":
            if idx + cols < total:
                idx += cols
        self._selected_idx = idx
        self._sync_selection()

    def on_key(self, event: Key) -> None:
        # Don't intercept keys when a modal/overlay/input is active
        if len(self.screen_stack) > 1:
            return
        focused = self.focused
        if focused is not None and not isinstance(focused, (AgentPane, EmptySlot)):
            return

        key = event.key
        nav_map = {
            "h": "left", "left": "left",
            "j": "down", "down": "down",
            "k": "up", "up": "up",
            "l": "right", "right": "right",
        }
        if key in nav_map:
            self._nav(nav_map[key])
            event.prevent_default()
            event.stop()
        elif key == "enter":
            panes = self._get_panes()
            if panes and 0 <= self._selected_idx < len(panes):
                self._do_attach(panes[self._selected_idx].agent_id)
            event.prevent_default()
            event.stop()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Grid(id="agent-grid")
        yield Static("Agents: 0/6 | [bold]hjkl[/]:Nav  [bold]Enter[/]:Open  [bold]n[/]:New  [bold]d[/]:Delete  [bold]r[/]:Refresh  [bold]q[/]:Quit", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        if not ensure_tmux():
            self.notify("tmux not found! Please install tmux.", severity="error")
            return
        self.manager.sync_from_tmux()
        self._rebuild_grid()
        self.set_interval(2.0, self._poll_agents)

    def _rebuild_grid(self) -> None:
        grid = self.query_one("#agent-grid", Grid)
        grid.remove_children()
        agents = list(self.manager.agents.values())

        for agent in agents[:6]:
            snippet = self.manager.get_snippet(agent.id, theme=self.current_theme)
            pane = AgentPane(agent)
            grid.mount(pane)
            pane.update_from_agent(agent, snippet)

        for _ in range(6 - len(agents)):
            grid.mount(EmptySlot())

        self.call_after_refresh(self._sync_selection)
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        count = len(self.manager.agents)
        perm_count = sum(
            1
            for a in self.manager.agents.values()
            if a.status == AgentStatus.NEEDS_PERMISSION
        )
        status = f"Agents: {count}/6"
        if perm_count:
            color = self.current_theme.secondary or "#7AA2F7"
            status += f" | [bold {color}]{perm_count} awaiting input[/]"
        status += " | [bold]hjkl[/]:Nav  [bold]Enter[/]:Open  [bold]n[/]:New  [bold]d[/]:Delete  [bold]r[/]:Refresh  [bold]q[/]:Quit"
        self.query_one("#status-bar", Static).update(status)

    def _poll_agents(self) -> None:
        self.manager.refresh_all()
        grid = self.query_one("#agent-grid", Grid)
        agents = list(self.manager.agents.values())

        pane_widgets = [c for c in grid.children if isinstance(c, AgentPane)]
        for pane in pane_widgets:
            agent = self.manager.agents.get(pane.agent_id)
            if agent:
                snippet = self.manager.get_snippet(agent.id, theme=self.current_theme)
                pane.update_from_agent(agent, snippet)

        # If agent count changed, full rebuild
        if len(pane_widgets) != len(agents):
            self._rebuild_grid()
        else:
            self._update_status_bar()

    def action_spawn_agent(self) -> None:
        home = os.path.expanduser("~")
        self.push_screen(SpawnDialog(start_dir=home), self._on_spawn_result)

    def _on_spawn_result(self, result: Optional[dict]) -> None:
        if result is None:
            return
        agent = self.manager.spawn(result["name"], result["dir"], result["command"])
        if agent is None:
            self.notify("Cannot spawn agent (max 6 or tmux error)", severity="error")
            return
        self.notify(f"Spawned {agent.name} in {agent.short_dir}")
        # Select the newly spawned agent
        self._selected_idx = len(self.manager.agents) - 1
        self._rebuild_grid()

    def action_delete_agent(self) -> None:
        panes = self._get_panes()
        if not panes:
            self.notify("No agents to delete", severity="warning")
            return
        idx = max(0, min(self._selected_idx, len(panes) - 1))
        pane = panes[idx]
        agent = self.manager.agents.get(pane.agent_id)
        if not agent:
            return
        self._delete_target = pane.agent_id
        self.push_screen(ConfirmDeleteDialog(agent.name), self._on_delete_result)

    def _on_delete_result(self, confirmed: bool) -> None:
        if not confirmed:
            return
        aid = self._delete_target
        agent = self.manager.agents.get(aid)
        name = agent.name if agent else aid
        if self.manager.remove(aid):
            self.notify(f"Removed {name}")
        else:
            self.notify(f"Failed to remove {name}", severity="error")
        # Clamp selection to remaining agents
        pane_count = len(self.manager.agents)
        if self._selected_idx >= pane_count and pane_count > 0:
            self._selected_idx = pane_count - 1
        self._rebuild_grid()

    def on_agent_pane_attach_request(self, message: AgentPane.AttachRequest) -> None:
        """Handle enter key from pane binding."""
        self._do_attach(message.agent_id)

    def _do_attach(self, agent_id: str) -> None:
        from .tmux import session_name, session_exists
        import os
        import sys

        name = session_name(agent_id)

        if not session_exists(agent_id):
            self.notify("Session no longer exists", severity="warning")
            return

        try:
            with self.suspend():
                # Use os.system for cleaner terminal handoff — subprocess.run
                # can leave terminal state inconsistent on some emulators
                # (notably Ghostty) when the child process (tmux attach)
                # manipulates the terminal directly.
                os.system(f"tmux attach-session -t {name}")
                # Reset terminal state after detach — some emulators don't
                # restore properly after tmux releases the tty
                os.system("stty sane 2>/dev/null")
        except Exception:
            # If suspend/resume fails, try to recover gracefully
            try:
                os.system("stty sane 2>/dev/null")
            except Exception:
                pass

        self.call_after_refresh(self._sync_selection)

    def action_refresh(self) -> None:
        self.manager.refresh_all()
        self._rebuild_grid()
        self.notify("Refreshed")



def main() -> None:
    app = OrcApp()
    app.run()


if __name__ == "__main__":
    main()
