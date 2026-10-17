"""Connect the LMS tool to whatever AI agents are on this computer, so the
person can just say "download my lectures" to their agent.

Different agents keep their settings in different files, but most share the
same shape. We detect the ones that are present and add our entry, leaving
everything else in their settings untouched.
"""
import json
import os
import shutil
import subprocess
import sys

SERVER_NAME = "lms"


def launch_command():
    """How an agent should start our MCP server. Prefer the installed
    `lms-mcp` command; fall back to running the module with this Python."""
    exe = shutil.which("lms-mcp")
    if exe:
        return exe, []
    return sys.executable, ["-m", "lmsgrab.mcp_server"]


def _home(*parts):
    return os.path.join(os.path.expanduser("~"), *parts)


def _generic_targets():
    """Agents that use the common {"mcpServers": {...}} shape."""
    t = []
    # Claude Desktop
    if sys.platform == "darwin":
        t.append(("Claude Desktop", _home("Library", "Application Support", "Claude",
                                          "claude_desktop_config.json")))
    elif os.name == "nt":
        appdata = os.environ.get("APPDATA", _home("AppData", "Roaming"))
        t.append(("Claude Desktop", os.path.join(appdata, "Claude", "claude_desktop_config.json")))
    else:
        t.append(("Claude Desktop", _home(".config", "Claude", "claude_desktop_config.json")))
    # Cursor
    t.append(("Cursor", _home(".cursor", "mcp.json")))
    # Windsurf
    t.append(("Windsurf", _home(".codeium", "windsurf", "mcp_config.json")))
    return t


def _load_json(path):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f) or {}
        except (json.JSONDecodeError, OSError):
            return None  # present but unreadable; don't clobber it
    return {}


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _wire_generic(name, path, only_existing):
    """Add our entry to a standard mcpServers config file."""
    exists = os.path.exists(path) or os.path.isdir(os.path.dirname(path))
    if only_existing and not exists:
        return None
    data = _load_json(path)
    if data is None:
        return f"{name}: left alone (its settings file looks hand-edited; add it yourself)"
    cmd, args = launch_command()
    data.setdefault("mcpServers", {})[SERVER_NAME] = {"command": cmd, "args": args}
    _save_json(path, data)
    return f"{name}: connected ({path})"


def _wire_opencode(only_existing):
    """opencode uses its own shape: mcp -> name -> {type, command[], enabled}."""
    path = _home(".config", "opencode", "opencode.json")
    if only_existing and not (os.path.exists(path) or os.path.isdir(os.path.dirname(path))):
        return None
    data = _load_json(path)
    if data is None:
        return f"opencode: left alone (settings file looks hand-edited)"
    cmd, args = launch_command()
    data.setdefault("mcp", {})[SERVER_NAME] = {
        "type": "local", "command": [cmd] + args, "enabled": True}
    _save_json(path, data)
    return f"opencode: connected ({path})"


def _wire_claude_code(only_existing):
    """Claude Code: use its own CLI if present (user scope)."""
    if not shutil.which("claude"):
        return None
    cmd, args = launch_command()
    try:
        r = subprocess.run(
            ["claude", "mcp", "add", "--scope", "user", SERVER_NAME, "--", cmd, *args],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return "Claude Code: connected (user scope)"
        if "already exists" in (r.stderr + r.stdout).lower():
            return "Claude Code: already connected"
        return f"Claude Code: could not add automatically ({r.stderr.strip()[:80]})"
    except Exception as e:
        return f"Claude Code: could not add automatically ({e})"


def setup(all_agents=False):
    """Connect to agents. By default only ones that appear installed;
    all_agents=True writes configs even if not detected yet.

    Returns a list of human-readable result lines."""
    out = []
    only_existing = not all_agents
    for name, path in _generic_targets():
        line = _wire_generic(name, path, only_existing)
        if line:
            out.append(line)
    line = _wire_opencode(only_existing)
    if line:
        out.append(line)
    line = _wire_claude_code(only_existing)
    if line:
        out.append(line)
    if not out:
        out.append("No AI agents detected. Run with --all to set them up anyway, "
                   "or the plain `lms` commands work without any agent.")
    return out
