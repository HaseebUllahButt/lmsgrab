#!/bin/sh
# One-line installer for lmsgrab.
#   curl -fsSL https://raw.githubusercontent.com/HaseebUllahButt/lmsgrab/main/install.sh | sh
#
# No pip needed — it's pure Python. This drops the code in your home area and
# puts an `lms` command on your PATH.
set -eu

OWNER_REPO="${LMSGRAB_REPO:-HaseebUllahButt/lmsgrab}"
BRANCH="${LMSGRAB_BRANCH:-main}"
APPDIR="${XDG_DATA_HOME:-$HOME/.local/share}/lmsgrab"
BINDIR="$HOME/.local/bin"
UPDATING=0
[ ! -d "$APPDIR/lmsgrab" ] || UPDATING=1

say() { printf '%s\n' "$*"; }

# --- need Python 3 ---------------------------------------------------------
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys;exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  say "Python 3 is needed but I couldn't find it. Please install Python 3 and run this again."
  exit 1
fi

say "Downloading lmsgrab..."
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
URL="https://codeload.github.com/$OWNER_REPO/tar.gz/refs/heads/$BRANCH"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$URL" -o "$TMP/src.tgz"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$TMP/src.tgz" "$URL"
else
  say "Need curl or wget to download. Please install one and retry."
  exit 1
fi

tar -xzf "$TMP/src.tgz" -C "$TMP"
SRC="$(find "$TMP" -maxdepth 1 -type d -name '*-*' | head -n1)"

# --- install the package ---------------------------------------------------
"$PY" "$SRC/lmsgrab/update.py" "$APPDIR"

# --- make the `lms` and `lms-mcp` commands --------------------------------
if ! (cd "$APPDIR" && "$PY" -m lmsgrab.install); then
  say "Application updated, but some setup needs attention. See the errors above."
  say "Fix the reported settings and rerun this installer; your login and downloads are kept."
  exit 1
fi
export PATH="$BINDIR:$PATH"

LMS="$BINDIR/lms"

if [ "$UPDATING" = 1 ]; then
  say "Update complete. Your saved login, download history and lectures are kept."
  say "Restart your AI apps to load the updated LMS tools."
  exit 0
fi

# If we can reach a real keyboard, go straight into setup: pick agents,
# log in, open one. (Probe in a subshell so a missing /dev/tty can't abort.)
if [ "${LMSGRAB_NO_START:-0}" != "1" ] && (exec </dev/tty) 2>/dev/null; then
  say ""
  "$LMS" start < /dev/tty || true
  exit 0
fi

say ""
say "All set. To begin:"
say "  lms start          # connect your AI agents, log in, and open one"
say ""
say "Or use it directly, no agent needed:"
say "  lms login          # log in once"
say "  lms download       # grab your lectures, sorted"
