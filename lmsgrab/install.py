"""Finish the dependency-free POSIX install: commands, PATH and AI apps."""
import os
from pathlib import Path
import shlex
import sys

from . import agents


def install_commands(bindir):
    bindir = Path(bindir)
    bindir.mkdir(parents=True, exist_ok=True)
    package = Path(__file__).resolve().parent
    for name, runner in (("lms", "run_cli.py"), ("lms-mcp", "run_mcp.py")):
        path = bindir / name
        path.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " +
                        shlex.quote(str(package / runner)) + ' "$@"\n', encoding="utf-8")
        path.chmod(0o755)


def install_path(bindir):
    """Persist PATH for new bash, zsh, sh and fish terminals, idempotently."""
    home = Path.home()
    marker = "# lmsgrab command path"
    path = shlex.quote(str(bindir))
    block = (f'\n{marker}\ncase ":$PATH:" in\n'
             f'  *:{path}:*) ;;\n  *) export PATH={path}:"$PATH" ;;\nesac\n')
    zdotdir = Path(os.environ.get("ZDOTDIR") or home)
    profiles = [home / ".profile", home / ".bashrc", zdotdir / ".zshrc", zdotdir / ".zprofile"]
    # Bash reads only its first existing login profile.
    profiles.extend(p for p in (home / ".bash_profile", home / ".bash_login") if p.exists())
    for profile in dict.fromkeys(profiles):
        original = profile.read_text(encoding="utf-8") if profile.exists() else ""
        if marker not in original:
            profile.parent.mkdir(parents=True, exist_ok=True)
            with profile.open("a", encoding="utf-8") as f:
                f.write(block)
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    fish = config / "fish" / "conf.d" / "lmsgrab.fish"
    fish.parent.mkdir(parents=True, exist_ok=True)
    # fish supports single quotes with escaped backslashes and single quotes.
    fish_path = str(bindir).replace("\\", "\\\\").replace("'", "\\'")
    fish.write_text(f"{marker}\ncontains -- '{fish_path}' $PATH; or set -gx PATH '{fish_path}' $PATH\n",
                    encoding="utf-8")


def main():
    bindir = Path.home() / ".local" / "bin"
    install_commands(bindir)
    install_path(bindir)
    print(f"Installed lms and lms-mcp in {bindir}. Open a new terminal to refresh PATH.")
    results = agents.setup()
    for line in results:
        print(line)
    print("Restart your AI app and start a new chat. Accept its LMS server trust prompt if shown.")
    if any("couldn't connect" in line for line in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
