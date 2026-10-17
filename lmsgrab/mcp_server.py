"""An MCP server so an AI agent (Claude Desktop, Claude Code, opencode,
Cursor, …) can run the LMS tool when you ask it to.

It speaks the MCP protocol directly over stdin/stdout (line-delimited
JSON-RPC), so there is nothing extra to install — standard library only.

The agent launches this automatically once it's wired up (see `lms setup-agent`).
It uses the login you saved with `lms login`.
"""
import json
import os
import sys

from . import __version__, engine, state
from .client import MoodleClient, LMSError

PROTOCOL = "2025-06-18"  # fallback; we echo whatever the client asks for


DEFAULT_URL = os.environ.get("LMS_URL", "https://lms.nust.edu.pk")

INSTRUCTIONS = (
    "LMS connects to the student's university learning management system (Moodle, "
    "including NUST LMS). Use these tools when asked about LMS, enrolled courses, "
    "lecture slides, lab manuals, course materials, downloading all lectures or new "
    "lectures, or submitting assignments. No project setup is needed. "
    "For an LMS request, call whoami first. If not logged in, guide the student to "
    "run lms login in a terminal. Reuse the saved login. For all lectures, call "
    "download_lectures without a course filter. Use only_new=true for new material. "
    "Report the actual output folder and any failures. Only submit work when asked; "
    "final=true hands it in for grading. Do not introduce LMS in unrelated chats."
)

# ---- the tools the agent can use -----------------------------------------
TOOLS = [
    {
        "name": "whoami",
        "description": "Check the saved university LMS / Moodle login. Call first for LMS requests.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "login",
        "description": ("Log in to the LMS with the student's username and password. "
                        "Ask them for these; the password is used once to get an access "
                        "key and is not stored."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "password": {"type": "string"},
                "url": {"type": "string",
                        "description": f"LMS web address. Optional; defaults to {DEFAULT_URL}."},
            },
            "required": ["username", "password"],
        },
    },
    {
        "name": "list_courses",
        "description": "List enrolled university LMS / Moodle courses with names and course IDs.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "download_lectures",
        "description": ("Download all my lectures, lecture slides, lab manuals and course files "
                        "from the university LMS / Moodle. Omit course to get every enrolled course. "
                        "Use only_new for 'get my new lectures'. Sorted into per-course folders "
                        "(Lectures / Labs / Assignments / Course Material), lectures "
                        "numbered by upload date. Reuses files the student already "
                        "has in their Downloads/Desktop/Documents. Saves into an "
                        "'LMS' folder in Downloads by default."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "only_new": {"type": "boolean",
                             "description": "Only fetch what changed since last time. Default false."},
                "include_books": {"type": "boolean",
                                  "description": "Include large textbooks/references. Default true."},
                "course": {"type": "string",
                           "description": "Limit to one course: its id or part of its name. Optional."},
                "out": {"type": "string", "description": "Folder to save into. Optional."},
            },
        },
    },
    {
        "name": "submit_assignment",
        "description": ("Hand in a file for an assignment. By default it saves a "
                        "draft; set final=true to submit for grading."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "course": {"type": "string", "description": "Course id or part of its name."},
                "assignment": {"type": "string", "description": "Assignment id or part of its name."},
                "file": {"type": "string", "description": "Path to the file on this computer."},
                "final": {"type": "boolean", "description": "Hand in for grading. Default false (draft)."},
            },
            "required": ["course", "assignment", "file"],
        },
    },
]


# ---- helpers --------------------------------------------------------------
def _client():
    cfg = state.load_config()
    if not cfg.get("token"):
        raise LMSError("Not logged in. Open a terminal and run:  lms login")
    return MoodleClient(cfg["url"], cfg["token"]), cfg


def _match_course(courses, wanted):
    wanted = str(wanted).strip().lower()
    import html as _html
    for c in courses:
        if str(c["id"]) == wanted:
            return c
    hits = [c for c in courses if wanted in _html.unescape(c.get("fullname", "")).lower()]
    return hits[0] if len(hits) == 1 else None


# ---- tool implementations -------------------------------------------------
def tool_whoami(args):
    cfg = state.load_config()
    if cfg.get("token"):
        return f"Logged in as {cfg.get('name')} ({cfg.get('url')})."
    return "Not logged in. Ask the student to run lms login in a terminal, then retry the LMS request."


def tool_login(args):
    from .client import MoodleClient
    url = (args.get("url") or DEFAULT_URL).rstrip("/")
    client = MoodleClient(url)
    client.login(args["username"], args["password"])
    info = client.site_info()
    state.save_config({"url": url, "token": client.token,
                       "userid": info["userid"], "name": info.get("fullname")})
    return f"Logged in as {info.get('fullname')}. Ready to go."


def tool_list_courses(args):
    import html as _html
    client, cfg = _client()
    courses = client.my_courses(cfg["userid"])
    lines = [f'[{c["id"]}] {_html.unescape(c.get("fullname",""))}' for c in courses]
    return "Your courses:\n" + "\n".join(lines)


def tool_download(args):
    client, cfg = _client()
    courses = client.my_courses(cfg["userid"])
    if args.get("course"):
        c = _match_course(courses, args["course"])
        if not c:
            return "Couldn't match that course. Use list_courses to see the exact names."
        courses = [c]
    out = args.get("out") or os.path.join(
        os.path.expanduser("~/Downloads") if os.path.isdir(os.path.expanduser("~/Downloads"))
        else os.path.expanduser("~"), "LMS")
    out = os.path.abspath(os.path.expanduser(out))
    manifest = state.load_manifest()
    res = engine.smart_download(
        client, courses, out,
        include_books=args.get("include_books", True),
        only_new=bool(args.get("only_new", False)),
        manifest=manifest)
    state.save_manifest(res["manifest"])
    if res["total"] == 0:
        return "Nothing new — the student is already up to date."
    return (f'Done. {res["downloaded"]} downloaded, {res["reused"]} reused from '
            f'existing files, {res["failed"]} failed. Everything is in: {res["out"]}')


def tool_submit(args):
    import html as _html
    client, cfg = _client()
    courses = client.my_courses(cfg["userid"])
    c = _match_course(courses, args["course"])
    if not c:
        return "Couldn't match that course. Use list_courses to see the exact names."
    path = os.path.expanduser(args["file"])
    if not os.path.exists(path):
        return f"File not found: {path}"
    assigns = client.call("mod_assign_get_assignments", **{"courseids[0]": c["id"]})
    found = [a for cc in assigns.get("courses", []) for a in cc.get("assignments", [])]
    wanted = str(args["assignment"]).strip().lower()
    match = [a for a in found if str(a["id"]) == wanted
             or wanted in _html.unescape(a["name"]).lower()]
    if not match:
        names = ", ".join(_html.unescape(a["name"]) for a in found) or "none"
        return f"No assignment matched. Available: {names}"
    if len(match) > 1:
        names = ", ".join(_html.unescape(a["name"]) for a in match)
        return f"That matched several: {names}. Be more specific."
    a = match[0]
    itemid = client.upload_to_draft(path)
    client.call("mod_assign_save_submission", assignmentid=a["id"],
                **{"plugindata[files_filemanager]": itemid})
    if args.get("final"):
        client.call("mod_assign_submit_for_grading", assignmentid=a["id"],
                    acceptsubmissionstatement=1)
        return f'Handed in "{os.path.basename(path)}" for grading on: {_html.unescape(a["name"])}'
    return (f'Saved "{os.path.basename(path)}" as a draft on: {_html.unescape(a["name"])}. '
            "Ask again with final=true to hand it in for grading.")


DISPATCH = {
    "whoami": tool_whoami,
    "login": tool_login,
    "list_courses": tool_list_courses,
    "download_lectures": tool_download,
    "submit_assignment": tool_submit,
}


# ---- the JSON-RPC loop ----------------------------------------------------
def _send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _result(rid, result):
    _send({"jsonrpc": "2.0", "id": rid, "result": result})


def _error(rid, code, message):
    _send({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})


def handle(req):
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        want = params.get("protocolVersion", PROTOCOL)
        _result(rid, {
            "protocolVersion": want,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "lmsgrab", "version": __version__},
            "instructions": INSTRUCTIONS,
        })
    elif method in ("notifications/initialized", "initialized"):
        pass  # notification, no reply
    elif method == "ping":
        _result(rid, {})
    elif method == "tools/list":
        _result(rid, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = DISPATCH.get(name)
        if not fn:
            return _error(rid, -32601, f"Unknown tool: {name}")
        try:
            text = fn(args)
            _result(rid, {"content": [{"type": "text", "text": text}]})
        except LMSError as e:
            _result(rid, {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True})
        except Exception as e:
            _result(rid, {"content": [{"type": "text", "text": f"Something went wrong: {e}"}],
                          "isError": True})
    elif rid is not None:
        _error(rid, -32601, f"Method not found: {method}")


def main():
    # Speak plain UTF-8 with "\n" line ends on every OS (Windows would
    # otherwise use its local code page and "\r\n").
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, ValueError):
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(req, list):           # batch
            for r in req:
                handle(r)
        else:
            handle(req)


if __name__ == "__main__":
    main()
