"""Stage and validate a downloaded package before replacing an installation.

Executed directly from the downloaded archive by both platform installers.
Only the application code is replaced; login, history and downloads live outside
this directory. Keep the previous code until the replacement passes its check.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile


def check_package(package):
    for name in ("__init__.py", "cli.py", "engine.py", "client.py", "state.py",
                 "agents.py", "install.py", "run_cli.py", "run_mcp.py", "mcp_server.py"):
        if not (package / name).is_file():
            raise ValueError("Download is incomplete: missing " + name)
    for path in package.rglob("*.py"):
        compile(path.read_bytes(), str(path), "exec")
    subprocess.run([sys.executable, str(package / "run_cli.py"), "--help"],
                   cwd=str(package.parent), check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=20)


def update_package(source, appdir):
    appdir = Path(appdir).resolve()
    source = Path(source).resolve()
    appdir.mkdir(parents=True, exist_ok=True)
    target = appdir / "lmsgrab"
    lock = appdir / ".install-lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise RuntimeError(f"Another installation may be running. If it was interrupted, remove {lock} and retry.")
    temp = None
    cleanup = True
    try:
        temp = Path(tempfile.mkdtemp(prefix=".lms-update-", dir=str(appdir)))
        staged = temp / "lmsgrab"
        backup = temp / "previous"
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        check_package(staged)
        existing = target.exists()
        if existing:
            os.replace(target, backup)
        try:
            os.replace(staged, target)
            check_package(target)
        except BaseException:
            try:
                if target.exists():
                    os.replace(target, temp / "failed")
                if existing:
                    os.replace(backup, target)
            except BaseException as e:
                cleanup = False
                raise RuntimeError(f"Automatic restore failed; previous files are preserved at {backup}: {e}") from e
            raise
        return existing
    finally:
        if temp is not None and cleanup:
            shutil.rmtree(temp)
        lock.rmdir()


def main():
    try:
        existing = update_package(Path(__file__).resolve().parent, sys.argv[1])
    except (OSError, ValueError, RuntimeError, SyntaxError, subprocess.SubprocessError) as e:
        sys.exit(f"Could not update LMS: {e}. Your saved login and downloads have not been changed.")
    print("Updated LMS application files." if existing else "Installed LMS application files.")


if __name__ == "__main__":
    main()
