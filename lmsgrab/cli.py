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

from . import engine, state
from .client import MoodleClient, LMSError

DEFAULT_URL = "https://lms.nust.edu.pk"


# ---- shared helpers -------------------------------------------------------
def _client():
    cfg = state.load_config()
    if not cfg.get("token"):
        sys.exit("Not logged in yet. Run:  lmsgrab login")
    return MoodleClient(cfg["url"], cfg["token"]), cfg


# ---- commands -------------------------------------------------------------
def cmd_login(args):
    url = args.url or input(f"Site URL [{DEFAULT_URL}]: ").strip() or DEFAULT_URL
    user = args.user or input("Username: ").strip()
    pw = args.password or getpass.getpass("Password: ")
    client = MoodleClient(url)
    try:
        client.login(user, pw)
    except LMSError as e:
        sys.exit(f"Login failed: {e}")
    info = client.site_info()
    state.save_config({"url": url.rstrip("/"), "token": client.token,
                       "userid": info["userid"], "name": info.get("fullname")})
    print(f"Logged in as {info.get('fullname')}. You're set.")


def cmd_status(args):
    cfg = state.load_config()
    if not cfg.get("token"):
        print("Not logged in. Run:  lmsgrab login")
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

    def start(self, i, total, name):
        self.i, self.total, self.name = i, total, name
        self.bdone = self.btot = 0
        self._render()

    def bytes(self, done, total):
        self.bdone, self.btot = done, total
        self._render()

    def finish(self, status):
        pass  # the next start() redraws; close() prints the final newline

    def _render(self):
        if not self.enabled or not self.total:
            return
        frac_file = (self.bdone / self.btot) if self.btot else 0.0
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
    out = os.path.abspath(args.out or _default_out())

    courses = client.my_courses(cfg["userid"])
    if args.course:
        courses = [c for c in courses if str(c["id"]) == str(args.course)]
        if not courses:
            sys.exit(f"No course with id {args.course}")

    # Decide whether to include books. If we're in a terminal and the student
    # didn't say, ask them (but only bother if there actually are books).
    include_books = True
    if getattr(args, "no_books", False):
        include_books = False
    elif not getattr(args, "books", False) and sys.stdin.isatty():
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
    res = engine.smart_download(
        client, courses, out, include_books=include_books, only_new=only_new,
        manifest=manifest, scan_dirs=scan_dirs, move=getattr(args, "move", False),
        on_file=None if live else (lambda m: print(f"  {m}")),
        progress=bar if live else None)
    bar.close()
    state.save_manifest(res["manifest"])

    if res["total"] == 0:
        print("Nothing new. You're all caught up." if only_new else "Nothing to download.")
        return []

    print(f'\nDone. {res["downloaded"]} downloaded, {res["reused"]} reused from your '
          f'folders, {res["failed"]} failed.')
    print(f'Everything is in: {res["out"]}')

    if args.zip and (res["downloaded"] or res["reused"]):
        zpath = out.rstrip("/") + ".zip"
        engine.make_zip(out, zpath)
        print(f"Zip: {zpath}")
    return res["files"]


def cmd_download(args):
    _download(args, only_new=False)


def cmd_new(args):
    _download(args, only_new=True)


def _tty_input(prompt):
    """Read a line from the real keyboard, even if stdin is a pipe
    (so this works right after a `curl | sh` install)."""
    try:
        with open("/dev/tty") as tty:
            sys.stdout.write(prompt)
            sys.stdout.flush()
            return tty.readline().strip()
    except OSError:
        try:
            return input(prompt)
        except EOFError:
            return ""


def cmd_start(args):
    from . import agents
    all_ = agents.detect()
    present = [a for a in all_ if a["present"]]
    menu = present or all_
    note = "" if present else " (none detected — pick the one you use)"

    print("Which AI agent do you want to use with your LMS?" + note + "\n")
    for i, a in enumerate(menu, 1):
        tag = "" if a["present"] else "  (not detected)"
        print(f"  {i}) {a['label']}{tag}")
    print(f"  0) Skip — I'll just use the 'lms' commands myself\n")

    choice = _tty_input("Enter a number: ").strip()
    if choice in ("", "0"):
        print("\nNo problem. Run 'lms login' then 'lms download' whenever you like.")
        return
    try:
        agent = menu[int(choice) - 1]
    except (ValueError, IndexError):
        sys.exit("That wasn't one of the choices. Run 'lms start' again.")

    print(f"\nSetting up {agent['label']}...")
    print("  " + agents.wire(agent))

    if agent["kind"] == "gui":
        agents.copy_to_clipboard(agents.STARTER_PROMPT)
        print("\nOpening the app. Fully quit and reopen it if it was already running.")
        print("Then start a new chat and paste this (already copied for you):\n")
        print("  " + agents.STARTER_PROMPT + "\n")
        if not agent["open"]():
            print("(Couldn't open it automatically — just open it yourself.)")
    else:
        print("\nOpening your agent now. It'll ask for your LMS login, then you're set.\n")
        if not agent["open"]():
            print("Couldn't launch it automatically. Open it yourself and say:")
            print("  " + agents.STARTER_PROMPT)


def cmd_setup_agent(args):
    from . import agents
    print("Connecting the LMS tool to your AI agent(s)...\n")
    for line in agents.setup(all_agents=args.all):
        print(f"  {line}")
    print("\nDone. Fully restart the agent app, then just ask it, e.g.:")
    print('   "download my new lectures"   or   "list my courses".')
    if not state.load_config().get("token"):
        print("\nFirst, log in once so the agent can act for you:  lms login")


def cmd_submit(args):
    client, cfg = _client()
    assigns = client.call("mod_assign_get_assignments", **{"courseids[0]": args.course})
    found = []
    for course in assigns.get("courses", []):
        for a in course.get("assignments", []):
            found.append(a)
    match = [a for a in found if str(a["id"]) == str(args.assignment)
             or args.assignment.lower() in html.unescape(a["name"]).lower()]
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
    path = args.file
    if not os.path.exists(path):
        sys.exit(f"File not found: {path}")
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
def main(argv=None):
    p = argparse.ArgumentParser(prog="lmsgrab", description="Your LMS, made simple.")
    sub = p.add_subparsers(dest="cmd", required=True)

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
        s.add_argument("--books", action="store_true", help="include textbooks without asking")
        s.add_argument("--no-books", action="store_true", help="skip textbooks")
        s.add_argument("--no-scan", action="store_true",
                       help="don't look for files you already downloaded")
        s.add_argument("--look", help="folder to check for files you already have")
        s.add_argument("--move", action="store_true",
                       help="move your existing files in instead of copying them")
        s.add_argument("--force", action="store_true", help="re-download even if already there")
        s.set_defaults(func=fn)

    sub.add_parser("start", help="pick an AI agent, connect it, and open it"
                   ).set_defaults(func=cmd_start)

    s = sub.add_parser("setup-agent", help="connect this tool to your AI agent(s)")
    s.add_argument("--all", action="store_true",
                   help="set up the known agents even if not detected yet")
    s.set_defaults(func=cmd_setup_agent)

    s = sub.add_parser("submit", help="hand in a file for an assignment")
    s.add_argument("course", help="course id (see: lmsgrab courses)")
    s.add_argument("assignment", help="assignment id or part of its name")
    s.add_argument("file", help="path to the file to submit")
    s.add_argument("--final", action="store_true", help="hand in for grading (not just save a draft)")
    s.set_defaults(func=cmd_submit)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except LMSError as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
