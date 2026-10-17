"""Remembers your login and what was downloaded last time, so we can later
fetch only the new stuff."""
import json
import os

APP = "lmsgrab"


def _config_dir():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = os.path.join(base, APP)
    os.makedirs(d, exist_ok=True)
    return d


def config_path():
    return os.path.join(_config_dir(), "config.json")


def manifest_path():
    return os.path.join(_config_dir(), "manifest.json")


def load_config():
    p = config_path()
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


def save_config(cfg):
    p = config_path()
    with open(p, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(p, 0o600)  # the token is in here; keep it private to you


def load_manifest():
    p = manifest_path()
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


def save_manifest(man):
    with open(manifest_path(), "w") as f:
        json.dump(man, f, indent=2)
