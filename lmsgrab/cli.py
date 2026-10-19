"""Command line for lmsgrab.

Commands:
  login     save your site + login once
  courses   list your courses
  download  download everything, sorted, into folders (and optionally a zip)
  new       download only what changed since last time
  submit    hand in a file for an assignment
  status    show who you are logged in as
"""
import argparse
import getpass
import html
import os
import sys
from urllib.error import URLError

from . import __version__, engine, state
from .client import MoodleClient, LMSError

DEFAULT_URL = "https://lms.nust.edu.pk"


# ---- shared helpers -------------------------------------------------------
def _client():
    cfg = state.load_config()
    if not cfg.get("token"):
        sys.exit("Not logged in yet. Run:  lms login")
    return MoodleClient(cfg["url"], cfg["token"]), cfg


# ---- commands -------------------------------------------------------------
def _do_login(url, user, pw):
    """Log in and save the access key. Raises LMSError on a wrong password."""
    client = MoodleClient(url)
    client.login(user, pw)
    info = client.site_info()
    state.save_config({"url": url.rstrip("/"), "token": client.token,
                       "userid": info["userid"], "name": info.get("fullname")})
    return info.get("fullname")


def cmd_login(args):
    url = args.url or input(f"Site URL [{DEFAULT_URL}]: ").strip() or DEFAULT_URL
    user = args.user or input("Username: ").strip()
    pw = args.password or getpass.getpass("Password: ")
    try:
        name = _do_login(url, user, pw)
    except LMSError as e:
        sys.exit(f"Login failed: {e}")
    print(f"Logged in as {name}. You're set.")


def cmd_status(args):
    cfg = state.load_config()
    if not cfg.get("token"):
        print("Not logged in. Run:  lms login")
        return
    print(f"Logged in as {cfg.get('name')}  ({cfg['url']})")


def cmd_courses(args):
    client, cfg = _client()
    courses = client.my_courses(cfg["userid"])
    for c in courses:
        print(f'  [{c["id"]:>5}]  {html.unescape(c.get("fullname",""))}')
    print(f"\n{len(courses)} courses.")


class Progress:
    """A live one-line progress bar: overall files done + the current file."""
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.i = self.total = 0
        self.name = ""
        self.bdone = self.btot = 0
        self.done = False

    def start(self, i, total, name):
        self.i, self.total, self.name = i, total, name
        self.bdone = self.btot = 0
        self.done = False
        self._render()

    def bytes(self, done, total):
        self.bdone, self.btot = done, total
        self._render()

    def finish(self, status):
        self.done = True
        self._render()

    def _render(self):
        if not self.enabled or not self.total:
            return
        frac_file = 1.0 if self.done else ((self.bdone / self.btot) if self.btot else 0.0)
        overall = ((self.i - 1) + frac_file) / self.total
        import shutil as _sh
        cols = min(_sh.get_terminal_size((80, 20)).columns, 100)
        barw = 22
        filled = int(barw * overall)
        bar = "█" * filled + "░" * (barw - filled)
        head = f"{self.i}/{self.total} [{bar}] {int(overall*100):3d}%  "
        room = max(10, cols - len(head) - 14)
        name = self.name if len(self.name) <= room else self.name[:room-1] + "…"
        tail = ""
        if self.btot:
            tail = f"  {self.bdone/1048576:.1f}/{self.btot/1048576:.1f}MB"
        line = head + name + tail
        sys.stdout.write("\r\033[K" + line[:cols])
        sys.stdout.flush()

    def close(self):
        if self.enabled and self.total:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()


def _default_out():
    dl = os.path.expanduser("~/Downloads")
    base = dl if os.path.isdir(dl) else os.path.expanduser("~")
    return os.path.join(base, "LMS")


def _ask_books(items):
    """If there are textbooks, ask whether to include them."""
    books = [it for it in items if it["book"]]
    if not books:
        return True
    print("\nFound these book/reference files (often large):")
    for b in books:
        mb = b["size"] / 1048576 if b["size"] else 0
        print(f'   - {b["filename"]}  ({mb:.0f} MB)' if mb else f'   - {b["filename"]}')
    ans = input("Include the books too? [y/N]: ").strip().lower()
    return ans in ("y", "yes")


def _download(args, only_new):
    client, cfg = _client()
    out = os.path.abspath(os.path.expanduser(args.out or _default_out()))

    print("Checking your courses and files…", flush=True)
    courses = client.my_courses(cfg["userid"])
    if args.course:
        courses = [c for c in courses if str(c["id"]) == str(args.course)]
        if not courses:
            sys.exit(f"No course with id {args.course}. Run 'lms courses' to see available IDs.")
    if not courses:
        print("No enrolled courses were found for this account.")
        return []

    # Decide whether to include books. If we're in a terminal and the student
    # didn't say, ask them (but only bother if there actually are books).
    include_books = False
    if getattr(args, "books", False):
        include_books = True
    elif not getattr(args, "no_books", False) and sys.stdin.isatty():
        peek = engine.collect_items(client, courses, include_books=True)
        include_books = _ask_books(peek)

    # Decide where to look for files already downloaded (or turn it off).
    if getattr(args, "no_scan", False):
        scan_dirs = False
    elif getattr(args, "look", None):
        scan_dirs = [args.look]
    else:
        scan_dirs = engine.DEFAULT_SCAN

    manifest = state.load_manifest()
    live = sys.stdout.isatty()
    bar = Progress(enabled=live)
    failures = []

    def report(message):
        if not live:
            print(f"  {message}")
        elif message.startswith("FAILED "):
            failures.append(message)

    try:
        res = engine.smart_download(
            client, courses, out, include_books=include_books, only_new=only_new,
            manifest=manifest, scan_dirs=scan_dirs, move=getattr(args, "move", False),
            on_file=report, progress=bar if live else None,
            force=getattr(args, "force", False))
    finally:
        bar.close()
    state.save_manifest(res["manifest"])

    if res["total"] == 0:
        print("Nothing new. You're all caught up." if only_new else "Nothing to download.")
        return []

    result = "Finished with errors." if res["failed"] else "Done."
    print(f'\n{result} {res["downloaded"]} downloaded, {res["reused"]} reused from your '
          f'folders, {res["skipped"]} already in place, {res["failed"]} failed.')
    for message in failures:
        print(f"  {message}")
    if res["files"]:
        print(f'Files are in: {res["out"]}')

    if args.zip and res["files"]:
        zpath = out.rstrip("/\\") + ".zip"
        engine.make_zip(out, zpath)
        print(f"Zip: {zpath}")
    if res["failed"]:
        print("Run the same command again to retry the failed files.")
        sys.exit(1)
    return res["files"]


def cmd_download(args):
    _download(args, only_new=False)


def cmd_new(args):
    _download(args, only_new=True)


def _tty_input(prompt):
    """Read a line from the real keyboard, even if stdin is a pipe
    (so this works right after a `curl | sh` install)."""
    try:
        with open("CONIN$" if os.name == "nt" else "/dev/tty") as tty:
            sys.stdout.write(prompt)
            sys.stdout.flush()
            return tty.readline().strip()
    except OSError:
        try:
            return input(prompt)
        except EOFError:
            return ""


def _pick_numbers(answer, count):
    """Turn "1 3" or "1,3" into [0, 2]. Reject invalid selections."""
    picks = []
    for part in answer.replace(",", " ").split():
        if not part.isdecimal() or not 1 <= int(part) <= count:
            return []
        if int(part) - 1 not in picks:
            picks.append(int(part) - 1)
    return picks


def _ask_login():
    """Make sure we're logged in, asking for username and password if not."""
    cfg = state.load_config()
    if cfg.get("token"):
        try:
            MoodleClient(cfg["url"], cfg["token"]).site_info()
            print(f"You're already logged in as {cfg.get('name')}.")
            return True
        except LMSError:
            pass  # saved login stopped working; ask again
        except Exception:
            return True  # no internet right now; keep the saved login
    print("Log in with your LMS username and password (same as the website).")
    print("Your password is only used once and is not saved.\n")
    for _ in range(3):
        user = _tty_input("LMS username: ")
        if not user:
            break
        pw = getpass.getpass("LMS password: ")
        try:
            name = _do_login(DEFAULT_URL, user, pw)
            print(f"\nLogged in as {name}.")
            return True
        except LMSError as e:
            print(f"That didn't work ({e}). Try again.\n")
        except Exception as e:
            print(f"Couldn't reach the LMS ({e}). Check your internet and try again.\n")
    print("Skipping login for now. Your agent will ask for it instead.")
    return False


def cmd_start(args):
    from . import agents
    found = [a for a in agents.detect() if a["present"]]

    # 1) Which agents get the LMS tool? All of them unless they say otherwise.
    if found:
        print("I found these AI apps on your computer:\n")
        for i, a in enumerate(found, 1):
            print(f"  {i}) {a['label']}")
        while True:
            ans = _tty_input("\nAdd the LMS tool: Enter for all, 0 to skip, "
                             "or numbers to select (like 1 3): ").strip()
            if not ans:
                picked = found
                break
            if ans == "0":
                picked = []
                break
            nums = _pick_numbers(ans, len(found))
            if nums:
                picked = [found[i] for i in nums]
                break
            print(f"Choose numbers from 1 to {len(found)}, 0 to skip, or Enter for all.")
        print()
        for a in picked:
            print("  " + agents.wire(a))
    else:
        picked = []
        print("I couldn't find an AI app on this computer (like Claude Code, Codex or OpenCode).")
        print("Install one, then run 'lms start' again. You can still use 'lms download'.")

    # 2) Log in to the LMS.
    print()
    _ask_login()

    if not picked:
        return

    # 3) Which one to open now?
    print("\nWhich one do you want to open now?\n")
    for i, a in enumerate(picked, 1):
        print(f"  {i}) {a['label']}")
    print("  0) None, I'll open it myself later")
    while True:
        choice = _tty_input("\nPress Enter for 1, or type a number: ").strip() or "1"
        if choice == "0":
            print("\nAll set. Open your agent any time and ask it about your LMS.")
            return
        if choice.isdecimal() and 1 <= int(choice) <= len(picked):
            agent = picked[int(choice) - 1]
            break
        print(f"Choose one number from 1 to {len(picked)}, or 0 to open none.")

    if agent["kind"] == "gui":
        agents.copy_to_clipboard(agents.STARTER_PROMPT)
        print(f"\nOpening {agent['label']}. Fully quit and reopen it if it was already running.")
        print("Then start a new chat and paste this (already copied for you):\n")
        print("  " + agents.STARTER_PROMPT + "\n")
        if not agent["open"]():
            print("(Couldn't open it automatically. Just open it yourself.)")
    else:
        print(f"\nOpening {agent['label']}. It already knows what to do, "
              "so just answer its questions.\n")
        if not agent["open"]():
            print("Couldn't launch it automatically. Open it yourself and say:")
            print("  " + agents.STARTER_PROMPT)


def cmd_setup_agent(args):
    from . import agents
    print("Connecting the LMS tool to your AI agent(s)...\n")
    results = agents.setup(all_agents=args.all)
    for line in results:
        print(f"  {line}")
    if any("couldn't connect" in line for line in results):
        sys.exit("Some apps couldn't be connected. Fix the settings reported above, then run lms setup-agent again.")
    print("\nDone. Fully restart the agent app, then just ask it, e.g.:")
    print('   "download my new lectures"   or   "list my courses".')
    if not state.load_config().get("token"):
        print("\nFirst, log in once so the agent can act for you:  lms login")


def cmd_submit(args):
    path = os.path.expanduser(args.file)
    if not os.path.isfile(path):
        sys.exit(f"File not found or not a regular file: {path}")
    wanted = args.assignment.strip()
    if not wanted:
        sys.exit("Enter an assignment name or ID.")
    client, cfg = _client()
    assigns = client.call("mod_assign_get_assignments", **{"courseids[0]": args.course})
    found = []
    for course in assigns.get("courses", []):
        for a in course.get("assignments", []):
            found.append(a)
    match = [a for a in found if str(a["id"]) == wanted]
    if not match:
        match = [a for a in found if wanted.lower() in html.unescape(a["name"]).lower()]
    if not match:
        print("Could not find that assignment. Available in this course:")
        for a in found:
            print(f'  [{a["id"]}] {html.unescape(a["name"])}')
        sys.exit(1)
    if len(match) > 1:
        print("That name matches more than one assignment. Be more specific or use the id:")
        for a in match:
            print(f'  [{a["id"]}] {html.unescape(a["name"])}')
        sys.exit(1)
    a = match[0]
    print(f'Submitting "{os.path.basename(path)}" to: {html.unescape(a["name"])}')
    itemid = client.upload_to_draft(path)
    client.call("mod_assign_save_submission", assignmentid=a["id"],
                **{"plugindata[files_filemanager]": itemid})
    if args.final:
        client.call("mod_assign_submit_for_grading", assignmentid=a["id"],
                    acceptsubmissionstatement=1)
        print("Submitted for grading (final).")
    else:
        print("Uploaded as a draft. Add --final to hand it in for grading.")


# ---- entry point ----------------------------------------------------------
def _setup_console():
    """Windows: turn on colours/line redraws, and never crash on odd characters."""
    if os.name == "nt":
        os.system("")  # enables the terminal's redraw codes for the progress bar
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    _setup_console()
    p = argparse.ArgumentParser(prog="lms", description="Your LMS, made simple.")
    p.add_argument("--version", action="version", version=f"lms {__version__}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("login", help="save your site and login once")
    s.add_argument("--url"); s.add_argument("--user"); s.add_argument("--password")
    s.set_defaults(func=cmd_login)

    sub.add_parser("status", help="show who you're logged in as").set_defaults(func=cmd_status)
    sub.add_parser("courses", help="list your courses").set_defaults(func=cmd_courses)

    for name, fn, helptext in [("download", cmd_download, "download everything, sorted"),
                               ("new", cmd_new, "download only what changed since last time")]:
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--out", help="folder to save into (default: a 'LMS' folder in Downloads)")
        s.add_argument("--course", help="limit to one course id")
        s.add_argument("--zip", action="store_true", help="also make a single zip file")
        books = s.add_mutually_exclusive_group()
        books.add_argument("--books", action="store_true", help="include textbooks without asking")
        books.add_argument("--no-books", action="store_true", help="skip textbooks")
        scan = s.add_mutually_exclusive_group()
        scan.add_argument("--no-scan", action="store_true",
                          help="don't look for files you already downloaded")
        scan.add_argument("--look", help="folder to check for files you already have")
        s.add_argument("--move", action="store_true",
                       help="move your existing files in instead of copying them")
        s.add_argument("--force", action="store_true",
                       help="fetch fresh copies from the LMS, including unchanged files")
        s.set_defaults(func=fn)

    sub.add_parser("start", help="connect your AI agents, log in, and open one"
                   ).set_defaults(func=cmd_start)

    s = sub.add_parser("setup-agent", help="connect this tool to your AI agent(s)")
    s.add_argument("--all", action="store_true",
                   help="set up the known agents even if not detected yet")
    s.set_defaults(func=cmd_setup_agent)

    s = sub.add_parser("submit", help="hand in a file for an assignment")
    s.add_argument("course", help="course id (see: lms courses)")
    s.add_argument("assignment", help="assignment id or part of its name")
    s.add_argument("file", help="path to the file to submit")
    s.add_argument("--final", action="store_true", help="hand in for grading (not just save a draft)")
    s.set_defaults(func=cmd_submit)

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return
    try:
        args.func(args)
    except LMSError as e:
        sys.exit(f"Error: {e}")
    except URLError as e:
        sys.exit(f"Could not reach the LMS: {e.reason}. Check your connection and try again.")
    except OSError as e:
        sys.exit(f"Could not complete the command: {e}")
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nCancelled.")


if __name__ == "__main__":
    main()
