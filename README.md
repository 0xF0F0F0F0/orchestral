# orchestral

TUI for managing and observing multiple AI coding agents running across different repositories.

Built with Python/Textual, uses tmux as the backend to manage agent sessions.

## features

- **overview grid** — see up to 6 agents at once with live output snippets
- **status borders** — blue when agent needs input, grey when running, green when done
- **vim navigation** — hjkl to move between panes, enter to open, d to delete
- **tmux attach** — drop into any agent's full terminal, detach back with ctrl-b d
- **theme support** — ships with 20+ themes (tokyo-night, dracula, catppuccin, etc.), persisted across sessions
- **auto-detect** — picks up repo name, git branch, and working directory from each agent
- **smart snippets** — strips TUI chrome from agent output, colorizes errors/tools/prompts

## keybindings

| key | action |
|-----|--------|
| h/j/k/l | navigate panes |
| enter | open selected agent (tmux attach) |
| n | spawn new agent |
| d | delete selected agent |
| r | refresh |
| q | quit |

## dependencies

- python 3.11+
- tmux
- [textual](https://github.com/Textualize/textual)

## setup

```sh
git clone git@github.com:0xF0F0F0F0/orchestral.git
cd orchestral
python -m venv .venv
source .venv/bin/activate
pip install textual
```

## run

```sh
python main.py
```

## config

Theme preference is saved to `~/.config/orchestral/config.json`.

Change themes with ctrl-p inside the app.
