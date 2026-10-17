"""Connect the LMS tool to the AI agent the student uses, and open it.

Each agent keeps its settings in a different place and starts in a different
way. This module knows how to detect the common ones, add our entry (without
disturbing anything else), and launch them with a friendly opening prompt.
Works on Mac, Linux and Windows.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

SERVER_NAME = "lms"
WINDOWS = os.name == "nt"
PRIORITY = {"claude-code", "codex", "opencode", "cursor", "antigravity", "copilot", "vscode"}

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


def _codex_config_path():
    return os.path.join(os.environ.get("CODEX_HOME") or _home(".codex"), "config.toml")


def _codex_present():
    return bool(shutil.which("codex")) or any(
        glob.glob(_home(folder, "extensions", "openai.chatgpt-*"))
        for folder in (".vscode", ".vscode-insiders", ".vscode-server", ".vscode-server-insiders", ".cursor"))


def _user_config(app):
    if WINDOWS:
        base = os.environ.get("APPDATA", _home("AppData", "Roaming"))
    elif sys.platform == "darwin":
        base = _home("Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or _home(".config")
    return os.path.join(base, app)


def _opencode_config():
    base = os.path.join(os.environ.get("XDG_CONFIG_HOME") or _home(".config"), "opencode")
    # JSONC overrides JSON in OpenCode; update the effective file.
    commented = os.path.join(base, "opencode.jsonc")
    return commented if os.path.exists(commented) else os.path.join(base, "opencode.json")


def _opencode_v2():
    exe = shutil.which("opencode")
    if not exe:
        return None
    try:
        result = subprocess.run([exe, "--version"], capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, timeout=10)
        version = re.search(r"(?:^|\s)v?(\d+)\.", result.stdout)
        return int(version[1]) >= 2 if version else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _vscode_paths():
    paths = [os.path.join(_user_config("Code"), "User", "mcp.json")]
    for app in ("Code", "Code - Insiders", "VSCodium", "Code - OSS"):
        root = os.path.join(_user_config(app), "User")
        if os.path.isdir(root):
            paths.append(os.path.join(root, "mcp.json"))
            paths.extend(glob.glob(os.path.join(root, "profiles", "*", "mcp.json")))
            paths.extend(os.path.join(p, "mcp.json") for p in glob.glob(os.path.join(root, "profiles", "*"))
                         if os.path.isdir(p))
    return list(dict.fromkeys(paths))


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
         "config": _home(".claude.json"), "shape": "mcpServers",
         "present": bool(shutil.which("claude")),
         "open": lambda: _run_cli(["claude", STARTER_PROMPT,
                                   "--allowedTools", f"mcp__{SERVER_NAME}"])},
        {"key": "codex", "label": "Codex (CLI / VS Code)",
         "kind": "cli" if shutil.which("codex") else "gui",
         "config": _codex_config_path(), "shape": "codex",
         "present": _codex_present(),
         "open": lambda: (_run_cli(["codex", STARTER_PROMPT]) if shutil.which("codex")
                          else _open_gui("code"))},
        {"key": "opencode", "label": "OpenCode", "kind": "cli",
         "config": _opencode_config(), "shape": "opencode",
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
         "config": _home(".cursor", "mcp.json"), "shape": "cursor",
         "present": bool(shutil.which("cursor")) or os.path.isdir(_home(".cursor")),
         "open": lambda: _open_gui("cursor")},
        {"key": "antigravity", "label": "Antigravity", "kind": "gui",
         "config": _home(".gemini", "config", "mcp_config.json"), "shape": "mcpServers",
         "extra_configs": [_home(".gemini", "antigravity", "mcp_config.json")],
         "present": bool(shutil.which("antigravity")) or os.path.isdir(_home(".gemini", "antigravity")),
         "open": lambda: _open_gui("antigravity")},
        {"key": "copilot", "label": "GitHub Copilot", "kind": "cli",
         "config": os.path.join(os.environ.get("COPILOT_HOME") or _home(".copilot"), "mcp-config.json"),
         "shape": "copilot", "present": bool(shutil.which("copilot")),
         "open": lambda: _run_cli(["copilot", "-i", STARTER_PROMPT])},
        {"key": "vscode", "label": "Copilot in VS Code", "kind": "gui",
         "config": _vscode_paths()[0], "extra_configs": _vscode_paths()[1:], "shape": "vscode",
         "present": bool(shutil.which("code")) or os.path.isdir(_user_config("Code")),
         "open": lambda: _open_gui("code")},
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
                source = f.read()
            if not source.strip():
                return {}
            # JSONC is accepted by editors and OpenCode. Keep string contents
            # (including https:// URLs) intact while removing comments/commas.
            source = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/',
                            lambda m: m[0] if m[0].startswith('"') else " ", source)
            source = re.sub(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])',
                            lambda m: m[0] if m[0].startswith('"') else "", source)
            data = json.loads(source)
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return None
    return {}


def _save_json(path, data):
    _save_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _save_text(path, text):
    from pathlib import Path
    import tempfile
    target = Path(path)
    if target.exists() and target.read_text(encoding="utf-8") == text:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, str(target) + ".lms-backup")
    fd, temp = tempfile.mkstemp(prefix=".lms-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if target.exists():
            os.chmod(temp, target.stat().st_mode & 0o777)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _wire_codex(path, cmd, args):
    """Edit only our TOML tables; no Codex CLI or third-party packages required."""
    from pathlib import Path
    target = Path(path)
    original = target.read_text(encoding="utf-8") if target.exists() else ""
    # Skip strings/comments so a table-looking line inside a multiline prompt
    # cannot be mistaken for a real table. Match quoted keys as well.
    token = re.compile(
        r'"""(?:\\.|(?!""")[\s\S])*"""|\'\'\'[\s\S]*?\'\'\'|'
        r'"(?:\\.|[^"\\])*"|\'[^\']*\'|\#[^\n]*|'
        r'(?P<table>^[ \t]*\[(?P<key>[^\n]+?)\][ \t]*(?:\#[^\n]*)?$)', re.MULTILINE)
    tables = [m for m in token.finditer(original) if m.group("table")]
    spans = []
    for i, match in enumerate(tables):
        keys = [part.strip().strip("\"'") for part in match.group("key").split(".")]
        if keys[:2] == ["mcp_servers", SERVER_NAME]:
            spans.append((match.start(), tables[i + 1].start() if i + 1 < len(tables) else len(original)))
    updated = original
    for start, end in reversed(spans):
        updated = updated[:start] + updated[end:]
    entry = ("\n[mcp_servers.lms]\ncommand = " + json.dumps(cmd, ensure_ascii=False) +
             "\nargs = " + json.dumps(args, ensure_ascii=False) +
             "\nenabled = true\nstartup_timeout_sec = 20\ntool_timeout_sec = 3600\n")
    updated = updated.rstrip() + "\n" + entry
    try:
        import tomllib
    except ImportError:
        # Python 3.8–3.10 have no TOML reader. Refuse unusual inline/dotted
        # definitions instead of risking a duplicate server definition.
        if re.search(r'^\s*(?:mcp_servers|lms)\s*(?:=|\.)', updated, re.MULTILINE):
            raise ValueError("unusual TOML layout; run setup with Python 3.11 or newer")
    else:
        tomllib.loads(original)
        tomllib.loads(updated)
    _save_text(path, updated)


def wire(agent):
    """Add our MCP entry for one agent. Returns a result message."""
    cmd, args = launch_command()
    shape = agent["shape"]
    label = agent["label"]
    if shape == "codex":
        try:
            _wire_codex(agent["config"], cmd, args)
        except (OSError, ValueError) as e:
            return f"{label}: couldn't connect ({e}). Settings left unchanged."
        return f"{label}: connected for every project ({agent['config']})."
    paths = [agent["config"]] + agent.get("extra_configs", [])
    results = []
    for path in paths:
        try:
            _wire_json(path, shape, cmd, args)
            results.append(f"{label}: connected for every project ({path}).")
        except (OSError, ValueError) as e:
            results.append(f"{label}: couldn't connect ({path}: {e}).")
    return "\n  ".join(results)


def _wire_json(path, shape, cmd, args):
    data = _load_json(path)
    if data is None:
        raise ValueError("invalid settings; file left unchanged")
    group = "mcp" if shape == "opencode" else "servers" if shape == "vscode" else "mcpServers"
    if not isinstance(data.setdefault(group, {}), dict):
        raise ValueError(f"{group} must be an object; file left unchanged")
    if shape == "opencode":
        version = _opencode_v2()
        modern = "servers" in data[group] or version is True or (version is None and not data[group])
        entry = {"type": "local", "command": [cmd] + args}
        if modern:
            servers = data[group].setdefault("servers", {})
            if not isinstance(servers, dict):
                raise ValueError("mcp.servers must be an object; file left unchanged")
            servers[SERVER_NAME] = entry
            data[group].pop(SERVER_NAME, None)
        else:
            entry["enabled"] = True
            data[group][SERVER_NAME] = entry
    else:
        entry = {"command": cmd, "args": args}
        if shape in ("vscode", "cursor"):
            entry["type"] = "stdio"
        elif shape == "copilot":
            entry.update({"type": "local", "tools": ["*"],
                          "description": "University LMS (Moodle): courses, lecture downloads, new files, assignments."})
        data[group][SERVER_NAME] = entry
    _save_json(path, data)


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
        # Prepare priority apps even when only an editor extension is installed,
        # or the app will be installed later. No CLI detection required.
        if all_agents or a["present"] or a["key"] in PRIORITY:
            out.append(wire(a))
    if not out:
        out.append("No AI agents detected. Install one, or use the plain `lms` commands.")
    return out
