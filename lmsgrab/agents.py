"""Connect the LMS tool to the AI agent the student uses, and open it.

Each agent keeps its settings in a different place and starts in a different
way. This module knows how to detect the common ones, add our entry (without
disturbing anything else), and launch them with a friendly opening prompt.
Works on Mac, Linux and Windows.
"""
import glob
import json
import os
import shutil
import subprocess
import sys

SERVER_NAME = "lms"
WINDOWS = os.name == "nt"

# Plain words only: on Windows this goes through cmd.exe, which mangles
# quotes and symbols like % ^ & | < >.
STARTER_PROMPT = (
    "Use the lms tool to help me with my university LMS. Call whoami first. "
    "If I am not logged in, ask for my LMS username and password and call login. "
    "Then list my courses and ask me what I want: download all my lectures sorted "
    "into folders, get only the new ones, or hand in an assignment. "
    "Keep replies short and simple."
)


def launch_command():
    """How an agent should start our MCP server: this Python, run on a file."""
    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_mcp.py")
    return sys.executable, [runner]


def _home(*p):
    return os.path.join(os.path.expanduser("~"), *p)


def _desktop_config_path():
    if sys.platform == "darwin":
        return _home("Library", "Application Support", "Claude", "claude_desktop_config.json")
    if WINDOWS:
        # The Microsoft Store build keeps its settings in a private folder.
        local = os.environ.get("LOCALAPPDATA", _home("AppData", "Local"))
        boxed = glob.glob(os.path.join(local, "Packages", "Claude_*", "LocalCache",
                                       "Roaming", "Claude"))
        if boxed:
            return os.path.join(boxed[0], "claude_desktop_config.json")
        return os.path.join(os.environ.get("APPDATA", _home("AppData", "Roaming")),
                            "Claude", "claude_desktop_config.json")
    return _home(".config", "Claude", "claude_desktop_config.json")


# --- the registry of agents we support ------------------------------------
# Order matters: this is the order of the menus, most popular first.
def _registry():
    return [
        {"key": "claude-code", "label": "Claude Code", "kind": "cli",
         "config": None, "shape": "claude-cli",
         "present": bool(shutil.which("claude")),
         "open": lambda: _run_cli(["claude", STARTER_PROMPT,
                                   "--allowedTools", f"mcp__{SERVER_NAME}"])},
        {"key": "codex", "label": "Codex", "kind": "cli",
         "config": None, "shape": "codex-cli",
         "present": bool(shutil.which("codex")),
         "open": lambda: _run_cli(["codex", STARTER_PROMPT])},
        {"key": "opencode", "label": "OpenCode", "kind": "cli",
         "config": _home(".config", "opencode", "opencode.json"), "shape": "opencode",
         "present": bool(shutil.which("opencode")),
         "open": lambda: _run_cli(["opencode", "--prompt", STARTER_PROMPT])},
        {"key": "claude-desktop", "label": "Claude Desktop (app)", "kind": "gui",
         "config": _desktop_config_path(), "shape": "mcpServers",
         "present": os.path.isdir(os.path.dirname(_desktop_config_path())),
         "open": _open_claude_desktop},
        {"key": "gemini", "label": "Gemini CLI", "kind": "cli",
         "config": _home(".gemini", "settings.json"), "shape": "mcpServers",
         "present": bool(shutil.which("gemini")),
         "open": lambda: _run_cli(["gemini", "-i", STARTER_PROMPT])},
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
            with open(path, encoding="utf-8") as f:
                return json.load(f) or {}
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return None
    return {}


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _run_quiet(cmd):
    exe = shutil.which(cmd[0])
    return subprocess.run([exe] + cmd[1:], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def wire(agent):
    """Add our MCP entry for one agent. Returns a result message."""
    cmd, args = launch_command()
    shape = agent["shape"]
    label = agent["label"]
    if shape in ("claude-cli", "codex-cli"):
        tool = "claude" if shape == "claude-cli" else "codex"
        if not shutil.which(tool):
            return f"{label}: the `{tool}` command isn't installed."
        scope = ["--scope", "user"] if tool == "claude" else []
        # Remove any old entry first so a reinstall points at the new copy.
        _run_quiet([tool, "mcp", "remove", *scope, SERVER_NAME])
        r = _run_quiet([tool, "mcp", "add", *scope, SERVER_NAME, "--", cmd, *args])
        if r.returncode == 0:
            return f"{label}: connected."
        return f"{label}: couldn't connect ({(r.stderr or r.stdout).strip()[:80]})"

    path = agent["config"]
    data = _load_json(path)
    if data is None:
        return f"{label}: settings file looks hand-edited; add it yourself."
    if shape == "opencode":
        data.setdefault("mcp", {})[SERVER_NAME] = {
            "type": "local", "command": [cmd] + args, "enabled": True}
    else:  # standard mcpServers
        data.setdefault("mcpServers", {})[SERVER_NAME] = {"command": cmd, "args": args}
    _save_json(path, data)
    return f"{label}: connected."


# --- launching -------------------------------------------------------------
def _run_cli(cmd):
    """Hand the terminal over to the agent."""
    exe = shutil.which(cmd[0])
    if not exe:
        return False
    if WINDOWS:
        # Windows can't swap one program for another in place; run it and
        # leave when it's closed.
        try:
            rc = subprocess.call([exe] + cmd[1:])
        except OSError:
            return False
        sys.exit(rc)
    try:
        os.execv(exe, [exe] + cmd[1:])  # does not return on success
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
        elif WINDOWS:
            local = os.environ.get("LOCALAPPDATA", _home("AppData", "Local"))
            exe = os.path.join(local, "AnthropicClaude", "claude.exe")
            if os.path.exists(exe):
                subprocess.Popen([exe])
            else:
                os.startfile("claude://")  # the app registers this link
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
                p.communicate(text.encode("utf-16-le" if cmd[0] == "clip" else "utf-8"))
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
