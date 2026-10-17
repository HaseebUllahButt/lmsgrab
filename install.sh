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

say() { printf '%s\n' "$*"; }

# --- need Python 3 ---------------------------------------------------------
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys;exit(0 if sys.version_info[0]==3 else 1)' 2>/dev/null; then
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
rm -rf "$APPDIR"
mkdir -p "$APPDIR"
cp -R "$SRC/lmsgrab" "$APPDIR/"

# --- make the `lms` and `lms-mcp` commands --------------------------------
mkdir -p "$BINDIR"
make_launcher() {
  # $1 = command name, $2 = python module
  cat > "$BINDIR/$1" <<EOF
#!/bin/sh
exec "$PY" -m "$2" "\$@"
EOF
  chmod +x "$BINDIR/$1"
  # the launcher needs to find the package:
  sed -i.bak "2i export PYTHONPATH=\"$APPDIR:\${PYTHONPATH:-}\"" "$BINDIR/$1" 2>/dev/null || true
  rm -f "$BINDIR/$1.bak"
}
make_launcher lms lmsgrab
make_launcher lms-mcp lmsgrab.mcp_server

say ""
say "Installed. The 'lms' command is in: $BINDIR"

# --- make sure that folder is on PATH -------------------------------------
case ":$PATH:" in
  *":$BINDIR:"*) ;;
  *)
    say ""
    say "Add this line to your shell profile (~/.bashrc or ~/.zshrc), then open a new terminal:"
    say "    export PATH=\"$BINDIR:\$PATH\""
    ;;
esac

LMS="$BINDIR/lms"

# If we can reach a real keyboard, offer to set up an agent right now.
# (Probe in a subshell so a missing /dev/tty can't abort this script.)
if (exec </dev/tty) 2>/dev/null; then
  printf '\nSet up an AI agent now so you can just chat with it? [Y/n] ' > /dev/tty
  ans=""; IFS= read -r ans </dev/tty || ans=""
  case "$ans" in
    n|N|no|NO) ;;
    *) "$LMS" start < /dev/tty || true; exit 0 ;;
  esac
fi

say ""
say "All set. To begin:"
say "  lms start          # pick your AI agent and open it (it asks for your login)"
say ""
say "Or use it directly, no agent needed:"
say "  lms login          # log in once"
say "  lms download       # grab your lectures, sorted"
