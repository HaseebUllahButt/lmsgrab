"""Connect the LMS tool to the AI agent the student uses, and open it.

Each agent keeps its settings in a different place and starts in a different
way. This module knows how to detect the common ones, add our entry (without
disturbing anything else), and launch them with a friendly opening prompt.
"""
import json
import os
import shutil
import subprocess
import sys

SERVER_NAME = "lms"

STARTER_PROMPT = (
    "Use the \"lms\" tool to help me with my university LMS. "
    "First call its whoami tool; if I'm not logged in, ask me for my LMS "
    "username and password and call login. Then tell me you can download my "
    "lectures sorted, fetch new ones, or submit work, and ask what I want."
)


def launch_command():
    """How an agent should start our MCP server."""
    exe = shutil.which("lms-mcp")
    if exe:
        return exe, []
    return sys.executable, ["-m", "lmsgrab.mcp_server"]


def _home(*p):
    return os.path.join(os.path.expanduser("~"), *p)


def _desktop_config_path():
    if sys.platform == "darwin":
        return _home("Library", "Application Support", "Claude", "claude_desktop_config.json")
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA", _home("AppData", "Roaming")),
                            "Claude", "claude_desktop_config.json")
    return _home(".config", "Claude", "claude_desktop_config.json")


# --- the registry of agents we support ------------------------------------
def _registry():
    return [
        {"key": "claude-desktop", "label": "Claude Desktop (app)", "kind": "gui",
         "config": _desktop_config_path(), "shape": "mcpServers",
         "present": os.path.isdir(os.path.dirname(_desktop_config_path())),
         "open": _open_claude_desktop},
        {"key": "claude-code", "label": "Claude Code (terminal)", "kind": "cli",
         "config": None, "shape": "claude-cli",
         "present": bool(shutil.which("claude")),
         "open": lambda: _run_cli(["claude", STARTER_PROMPT])},
        {"key": "opencode", "label": "opencode (terminal)", "kind": "cli",
         "config": _home(".config", "opencode", "opencode.json"), "shape": "opencode",
         "present": bool(shutil.which("opencode")) or os.path.isdir(_home(".config", "opencode")),
         "open": lambda: _run_cli(["opencode"])},
        {"key": "cursor", "label": "Cursor (editor)", "kind": "gui",
         "config": _home(".cursor", "mcp.json"), "shape": "mcpServers",
         "present": bool(shutil.which("cursor")) or os.path.isdir(_home(".cursor")),
         "open": lambda: _open_gui("cursor")},
        {"key": "windsurf", "label": "Windsurf (editor)", "kind": "gui",
         "config": _home(".codeium", "windsurf", "mcp_config.json"), "shape": "mcpServers",
         "present": bool(shutil.which("windsurf")) or os.path.isdir(_home(".codeium", "windsurf")),
         "open": lambda: _open_gui("windsurf")},
    ]


def detect():
    """All known agents, each marked present or not."""
    return _registry()


# --- writing config --------------------------------------------------------
def _load_json(path):
    if path and os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f) or {}
        except (json.JSONDecodeError, OSError):
            return None
    return {}


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def wire(agent):
    """Add our MCP entry for one agent. Returns a result message."""
    cmd, args = launch_command()
    shape = agent["shape"]
    if shape == "claude-cli":
        if not shutil.which("claude"):
            return "Claude Code: the `claude` command isn't installed."
        r = subprocess.run(["claude", "mcp", "add", "--scope", "user", SERVER_NAME, "--", cmd, *args],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return "Claude Code: connected."
        if "already exists" in (r.stderr + r.stdout).lower():
            return "Claude Code: already connected."
        return f"Claude Code: couldn't connect ({r.stderr.strip()[:80]})"

    path = agent["config"]
    data = _load_json(path)
    if data is None:
        return f"{agent['label']}: settings file looks hand-edited; add it yourself."
    if shape == "opencode":
        data.setdefault("mcp", {})[SERVER_NAME] = {
            "type": "local", "command": [cmd] + args, "enabled": True}
    else:  # standard mcpServers
        data.setdefault("mcpServers", {})[SERVER_NAME] = {"command": cmd, "args": args}
    _save_json(path, data)
    return f"{agent['label']}: connected."


# --- launching -------------------------------------------------------------
def _run_cli(cmd):
    """Replace this process with the agent so it takes over the terminal."""
    exe = shutil.which(cmd[0])
    if not exe:
        return False
    try:
        os.execvp(exe, cmd)  # does not return on success
    except OSError:
        return False


def _open_gui(cmd):
    exe = shutil.which(cmd)
    if exe:
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    return False


def _open_claude_desktop():
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Claude"])
        elif os.name == "nt":
            os.startfile("claude")  # best effort
        else:
            exe = shutil.which("claude-desktop") or shutil.which("Claude")
            if exe:
                subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                return False
        return True
    except Exception:
        return False


def copy_to_clipboard(text):
    """Best-effort copy, so a GUI user can just paste the opening prompt."""
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["clip"]):
        exe = shutil.which(cmd[0])
        if exe:
            try:
                p = subprocess.Popen([exe] + cmd[1:], stdin=subprocess.PIPE)
                p.communicate(text.encode())
                return True
            except Exception:
                continue
    return False


# --- used by `lms setup-agent` (non-interactive, wire everything present) --
def setup(all_agents=False):
    out = []
    for a in detect():
        if all_agents or a["present"]:
            out.append(wire(a))
    if not out:
        out.append("No AI agents detected. Install one, or use the plain `lms` commands.")
    return out
