"""tmux backend - manages sessions and panes for AI agents."""

import subprocess
import shutil

SESSION_PREFIX = "orchestral"


def _run(cmd: list[str], check: bool = True) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=check)
    return result.stdout.strip()


def ensure_tmux() -> bool:
    return shutil.which("tmux") is not None


def session_name(agent_id: str) -> str:
    return f"{SESSION_PREFIX}-{agent_id}"


def create_session(agent_id: str, working_dir: str, command: str) -> bool:
    name = session_name(agent_id)
    try:
        _run([
            "tmux", "new-session",
            "-d",  # detached
            "-s", name,
            "-c", working_dir,
            command,
        ])
        return True
    except subprocess.CalledProcessError:
        return False


def kill_session(agent_id: str) -> bool:
    name = session_name(agent_id)
    try:
        _run(["tmux", "kill-session", "-t", name])
        return True
    except subprocess.CalledProcessError:
        return False


def session_exists(agent_id: str) -> bool:
    name = session_name(agent_id)
    try:
        _run(["tmux", "has-session", "-t", name])
        return True
    except subprocess.CalledProcessError:
        return False


def capture_pane(agent_id: str, lines: int = 40) -> str:
    """Capture the last N lines of output from an agent's tmux pane."""
    name = session_name(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", name, "-p", "-S", str(-lines)],
            capture_output=True, text=True, check=True,
        )
        # Don't strip — preserve structure, but remove trailing blank lines
        text = result.stdout.rstrip("\n")
        return text
    except subprocess.CalledProcessError:
        return ""


def get_pane_cwd(agent_id: str) -> str | None:
    """Get the current working directory of the agent's tmux pane process."""
    name = session_name(agent_id)
    try:
        pid = _run(["tmux", "display-message", "-t", name, "-p", "#{pane_pid}"])
        if pid:
            # Get cwd of the deepest child process
            child_pid = _run(
                ["bash", "-c", f"pgrep -P {pid} | tail -1"],
                check=False,
            )
            target_pid = child_pid or pid
            cwd = _run(["readlink", f"/proc/{target_pid}/cwd"], check=False)
            return cwd if cwd else None
    except Exception:
        pass
    return None


def get_git_branch(directory: str) -> str | None:
    """Get the current git branch for a directory."""
    try:
        branch = _run(
            ["git", "-C", directory, "rev-parse", "--abbrev-ref", "HEAD"],
            check=False,
        )
        return branch if branch else None
    except Exception:
        return None


def get_git_repo_name(directory: str) -> str | None:
    """Get the git repo root folder name."""
    try:
        root = _run(
            ["git", "-C", directory, "rev-parse", "--show-toplevel"],
            check=False,
        )
        if root:
            return root.split("/")[-1]
    except Exception:
        pass
    return None


def send_keys(agent_id: str, keys: str) -> bool:
    """Send keystrokes to an agent's tmux pane."""
    name = session_name(agent_id)
    try:
        _run(["tmux", "send-keys", "-t", name, keys, "Enter"])
        return True
    except subprocess.CalledProcessError:
        return False


def list_orchestral_sessions() -> list[str]:
    """List all orchestral tmux sessions, return agent IDs."""
    try:
        output = _run(["tmux", "list-sessions", "-F", "#{session_name}"], check=False)
        if not output:
            return []
        sessions = output.splitlines()
        return [
            s.removeprefix(f"{SESSION_PREFIX}-")
            for s in sessions
            if s.startswith(f"{SESSION_PREFIX}-")
        ]
    except Exception:
        return []


def attach_session(agent_id: str) -> None:
    """Attach to a session (used when user wants full-screen view)."""
    name = session_name(agent_id)
    subprocess.run(["tmux", "attach-session", "-t", name])
