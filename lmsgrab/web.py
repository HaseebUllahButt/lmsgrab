"""A tiny website wrapper so non-technical people can use the LMS tool.

They open the page, type their own LMS username and password, and click a
button to download a sorted zip, grab only new files, or submit a file.

Passwords are used once to log in, then thrown away. We keep only a short
lived in-memory session and, per user, a small list of what they already
downloaded (so "new only" works). No passwords are ever stored.

Run it:   python3 -m lmsgrab.web --port 8000
Then open http://localhost:8000
"""
import html
import io
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from . import engine
from .client import MoodleClient, LMSError

DEFAULT_URL = os.environ.get("LMS_URL", "https://lms.nust.edu.pk")
# Where per-user "what I already have" lists live (keyed by user id).
STATE_DIR = os.environ.get("LMS_STATE_DIR",
                           os.path.join(tempfile.gettempdir(), "lmsgrab-web-state"))
os.makedirs(STATE_DIR, exist_ok=True)

SESSIONS = {}            # sid -> {token, userid, name, url, ts}
SESSION_TTL = 60 * 60    # one hour
_LOCK = threading.Lock()


# ---- session + per-user manifest helpers ---------------------------------
def _new_session(client, info, url):
    sid = secrets.token_urlsafe(24)
    with _LOCK:
        SESSIONS[sid] = {"token": client.token, "userid": info["userid"],
                         "name": info.get("fullname"), "url": url, "ts": time.time()}
    return sid


def _get_session(sid):
    with _LOCK:
        s = SESSIONS.get(sid)
        if not s:
            return None
        if time.time() - s["ts"] > SESSION_TTL:
            SESSIONS.pop(sid, None)
            return None
        s["ts"] = time.time()
        return dict(s)


def _manifest_file(userid):
    return os.path.join(STATE_DIR, f"{userid}.json")


def _load_manifest(userid):
    p = _manifest_file(userid)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def _save_manifest(userid, man):
    with open(_manifest_file(userid), "w") as f:
        json.dump(man, f)


def parse_multipart(content_type, body):
    """Minimal multipart/form-data reader. Returns (fields, files) where
    fields maps name->text and files maps name->(filename, bytes)."""
    fields, files = {}, {}
    m = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            m = part[len("boundary="):].strip('"')
    if not m:
        return fields, files
    sep = b"--" + m.encode()
    for chunk in body.split(sep):
        if not chunk or chunk in (b"--\r\n", b"--", b"\r\n"):
            continue
        chunk = chunk.strip(b"\r\n")
        if b"\r\n\r\n" not in chunk:
            continue
        rawhead, value = chunk.split(b"\r\n\r\n", 1)
        head = rawhead.decode(errors="replace")
        name, filename = None, None
        for hl in head.split("\r\n"):
            if hl.lower().startswith("content-disposition"):
                for piece in hl.split(";"):
                    piece = piece.strip()
                    if piece.startswith("name="):
                        name = piece[5:].strip('"')
                    elif piece.startswith("filename="):
                        filename = piece[9:].strip('"')
        if name is None:
            continue
        if filename is not None:
            files[name] = (filename, value)
        else:
            fields[name] = value.decode(errors="replace")
    return fields, files


# ---- pages ----------------------------------------------------------------
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>My LMS</title><style>
:root{{--bg:#0f1221;--card:#1a1f38;--text:#eef1ff;--dim:#9aa3c7;--line:#2c3356;--accent:#6c8cff}}
*{{box-sizing:border-box}}
body{{margin:0;font:16px/1.5 system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text)}}
.wrap{{max-width:640px;margin:0 auto;padding:24px 16px}}
h1{{font-size:1.6rem;margin:.2em 0}}
.sub{{color:var(--dim);margin-top:0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;margin:16px 0}}
label{{display:block;margin:12px 0 4px;color:var(--dim);font-size:.9rem}}
input,select{{width:100%;padding:12px;border-radius:10px;border:1px solid var(--line);background:#11152b;color:var(--text);font-size:1rem}}
button{{width:100%;padding:14px;margin-top:14px;border:0;border-radius:12px;background:var(--accent);color:#fff;font-size:1.05rem;font-weight:600;cursor:pointer}}
button.ghost{{background:transparent;border:1px solid var(--line);color:var(--text)}}
.row{{display:flex;gap:12px}} .row>*{{flex:1}}
.note{{color:var(--dim);font-size:.85rem}}
.err{{background:#3a1420;border:1px solid #7a2740;color:#ffd4dd;padding:12px;border-radius:10px;margin:12px 0}}
.ok{{background:#12311f;border:1px solid #2a6b45;color:#c9ffd9;padding:12px;border-radius:10px;margin:12px 0}}
a{{color:var(--accent)}}
</style></head><body><div class="wrap">{body}</div></body></html>"""


def login_page(msg=""):
    err = f'<div class="err">{html.escape(msg)}</div>' if msg else ""
    return PAGE.format(body=f"""
<h1>My LMS</h1>
<p class="sub">Get all your lectures, sorted, in one zip. Log in with your LMS account.</p>
{err}
<div class="card">
<form method="post" action="/login">
<label>LMS username</label>
<input name="user" autocomplete="username" required autofocus>
<label>Password</label>
<input name="password" type="password" autocomplete="current-password" required>
<button type="submit">Log in</button>
<p class="note">Your password is used only to log in, then forgotten. It is never saved.</p>
</form>
</div>""")


def dashboard(sess, msg="", err=""):
    okbox = f'<div class="ok">{msg}</div>' if msg else ""
    errbox = f'<div class="err">{html.escape(err)}</div>' if err else ""
    return PAGE.format(body=f"""
<h1>Hi {html.escape((sess['name'] or '').split()[0] if sess['name'] else 'there')}</h1>
<p class="sub">What would you like to do?</p>
{okbox}{errbox}
<div class="card">
<form method="post" action="/download">
<button name="mode" value="all" type="submit">⬇ Download everything (zip)</button>
<button name="mode" value="new" type="submit" class="ghost">✨ Only what's new since last time</button>
</form>
<p class="note">Sorted into each course, with Lectures, Labs, Assignments and Course Material kept apart.</p>
</div>
<div class="card">
<h3 style="margin-top:0">Submit a file</h3>
<form method="post" action="/submit" enctype="multipart/form-data">
<label>Course</label>
<select name="course" required>{course_options(sess)}</select>
<label>Assignment name (or part of it)</label>
<input name="assignment" placeholder="e.g. Assignment 01" required>
<label>Your file</label>
<input name="file" type="file" required>
<label style="display:flex;gap:8px;align-items:center;margin-top:14px">
<input type="checkbox" name="final" value="1" style="width:auto"> Hand in for grading (otherwise saved as a draft)</label>
<button type="submit">Submit</button>
</form>
</div>
<p class="note"><a href="/logout">Log out</a></p>""")


def course_options(sess):
    client = MoodleClient(sess["url"], sess["token"])
    try:
        courses = client.my_courses(sess["userid"])
    except Exception:
        return ""
    return "".join(
        f'<option value="{c["id"]}">{html.escape(html.unescape(c.get("fullname","")))}</option>'
        for c in courses)


# ---- request handler ------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def _send(self, body, status=200, headers=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        for k, v in (headers or {"Content-Type": "text/html; charset=utf-8"}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sid(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            if part.strip().startswith("sid="):
                return part.strip()[4:]
        return None

    def _session(self):
        sid = self._sid()
        return _get_session(sid) if sid else None

    def do_GET(self):
        if self.path == "/logout":
            sid = self._sid()
            if sid:
                with _LOCK:
                    SESSIONS.pop(sid, None)
            return self._send("", 303, {"Location": "/", "Set-Cookie": "sid=; Max-Age=0; Path=/"})
        sess = self._session()
        if self.path in ("/", "") :
            return self._send(dashboard(sess) if sess else login_page())
        self._send("Not found", 404, {"Content-Type": "text/plain"})

    def _read_form(self):
        length = int(self.headers.get("Content-Length", 0))
        return parse_qs(self.rfile.read(length).decode())

    def do_POST(self):
        if self.path == "/login":
            return self._handle_login()
        sess = self._session()
        if not sess:
            return self._send("", 303, {"Location": "/"})
        if self.path == "/download":
            return self._handle_download(sess)
        if self.path == "/submit":
            return self._handle_submit(sess)
        self._send("Not found", 404, {"Content-Type": "text/plain"})

    def _handle_login(self):
        form = self._read_form()
        user = (form.get("user", [""])[0]).strip()
        pw = form.get("password", [""])[0]
        client = MoodleClient(DEFAULT_URL)
        try:
            client.login(user, pw)
            info = client.site_info()
        except LMSError:
            return self._send(login_page("That username or password didn't work. Try again."))
        except Exception as e:
            return self._send(login_page(f"Could not reach the LMS: {e}"))
        sid = _new_session(client, info, DEFAULT_URL)
        self._send("", 303, {"Location": "/",
                   "Set-Cookie": f"sid={sid}; HttpOnly; Path=/; Max-Age={SESSION_TTL}; SameSite=Lax"})

    def _handle_download(self, sess):
        form = self._read_form()
        only_new = form.get("mode", ["all"])[0] == "new"
        client = MoodleClient(sess["url"], sess["token"])
        tmp = tempfile.mkdtemp(prefix="lmsgrab-")
        try:
            courses = client.my_courses(sess["userid"])
            manifest = _load_manifest(sess["userid"])
            grabbed, skipped, new_manifest = engine.download_courses(
                client, courses, tmp, manifest=manifest, only_new=only_new)
            _save_manifest(sess["userid"], new_manifest)
            if not grabbed:
                msg = ("You're all caught up — nothing new since last time."
                       if only_new else "Nothing to download was found.")
                return self._send(dashboard(sess, msg=msg))
            buf = io.BytesIO()
            import zipfile
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for root, _, files in os.walk(tmp):
                    for fn in files:
                        full = os.path.join(root, fn)
                        z.write(full, os.path.relpath(full, tmp))
            data = buf.getvalue()
            name = "LMS-new.zip" if only_new else "LMS.zip"
            self._send(data, 200, {
                "Content-Type": "application/zip",
                "Content-Disposition": f'attachment; filename="{name}"'})
        except Exception as e:
            self._send(dashboard(sess, err=f"Something went wrong: {e}"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _handle_submit(self, sess):
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        fields, files = parse_multipart(ctype, body)
        course = fields.get("course")
        wanted = (fields.get("assignment") or "").strip()
        final = fields.get("final") == "1"
        fileitem = files.get("file")  # (filename, bytes)
        if not (course and wanted and fileitem and fileitem[0]):
            return self._send(dashboard(sess, err="Please pick a course, an assignment, and a file."))
        client = MoodleClient(sess["url"], sess["token"])
        tmp = tempfile.mkdtemp(prefix="lmsgrab-up-")
        try:
            path = os.path.join(tmp, os.path.basename(fileitem[0]))
            with open(path, "wb") as f:
                f.write(fileitem[1])
            assigns = client.call("mod_assign_get_assignments", **{"courseids[0]": course})
            found = [a for c in assigns.get("courses", []) for a in c.get("assignments", [])]
            match = [a for a in found if wanted.lower() in html.unescape(a["name"]).lower()
                     or str(a["id"]) == wanted]
            if not match:
                names = ", ".join(html.unescape(a["name"]) for a in found) or "none"
                return self._send(dashboard(sess, err=f"No assignment matched “{wanted}”. Available: {names}"))
            if len(match) > 1:
                names = ", ".join(html.unescape(a["name"]) for a in match)
                return self._send(dashboard(sess, err=f"That matched several: {names}. Be more specific."))
            a = match[0]
            itemid = client.upload_to_draft(path)
            client.call("mod_assign_save_submission", assignmentid=a["id"],
                        **{"plugindata[files_filemanager]": itemid})
            if final:
                client.call("mod_assign_submit_for_grading", assignmentid=a["id"],
                            acceptsubmissionstatement=1)
                msg = f"Handed in “{html.escape(os.path.basename(fileitem[0]))}” for grading."
            else:
                msg = (f"Saved “{html.escape(os.path.basename(fileitem[0]))}” as a draft. "
                       "Tick the grading box to hand it in.")
            self._send(dashboard(sess, msg=msg))
        except Exception as e:
            self._send(dashboard(sess, err=f"Could not submit: {e}"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def log_message(self, *a):
        pass  # keep the console quiet


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="lmsgrab.web", description="Run the LMS website.")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"LMS site running. Open http://localhost:{args.port}  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
