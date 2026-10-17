"""Talks to a Moodle site through its mobile web-service door.

Stdlib only, so it runs anywhere Python does. Handles two quirks of the
NUST server: an old TLS handshake, and a missing certificate link that we
fetch and cache ourselves (we keep verification ON).
"""
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request

OP_LEGACY_SERVER_CONNECT = 0x4  # allow the server's old-style handshake


class LMSError(Exception):
    pass


def _cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    d = os.path.join(base, "lmsgrab")
    os.makedirs(d, exist_ok=True)
    return d


def _build_ssl_context(host):
    """A verifying context that also tolerates this server's two quirks."""
    ctx = ssl.create_default_context()
    ctx.options |= OP_LEGACY_SERVER_CONNECT
    extra = os.path.join(_cache_dir(), f"{host}.intermediate.pem")
    if os.path.exists(extra):
        try:
            ctx.load_verify_locations(cafile=extra)
        except ssl.SSLError:
            pass
    return ctx


def _fetch_missing_intermediate(host, port=443):
    """The server forgets to send one certificate link. Download it from the
    address printed inside its own certificate, convert, and cache it."""
    ctx = ssl._create_unverified_context()
    ctx.options |= OP_LEGACY_SERVER_CONNECT
    import socket
    with socket.create_connection((host, port), timeout=30) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            der = ssock.getpeercert(binary_form=True)
    # Parse the "CA Issuers" URL out of the certificate.
    text = ssl.DER_cert_to_PEM_cert(der)
    # Read the "CA Issuers" address out of the certificate using openssl.
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
        f.write(text)
        leaf = f.name
    try:
        out = subprocess.run(
            ["openssl", "x509", "-in", leaf, "-noout", "-text"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    finally:
        os.unlink(leaf)
    m = re.search(r"CA Issuers - URI:(\S+)", out)
    if not m:
        raise LMSError("could not find the missing certificate link")
    url = m.group(1)
    raw = urllib.request.urlopen(url, timeout=30).read()
    # It arrives in binary (DER); convert to PEM with openssl.
    p = subprocess.run(
        ["openssl", "x509", "-inform", "der", "-outform", "pem"],
        input=raw, capture_output=True, timeout=30,
    )
    pem = p.stdout
    dest = os.path.join(_cache_dir(), f"{host}.intermediate.pem")
    with open(dest, "wb") as f:
        f.write(pem)
    return dest


class MoodleClient:
    def __init__(self, base_url, token=None):
        self.base_url = base_url.rstrip("/")
        self.host = urllib.parse.urlparse(self.base_url).hostname
        self.token = token
        self.ctx = _build_ssl_context(self.host)

    # -- low level ---------------------------------------------------------
    def _open(self, req):
        try:
            return urllib.request.urlopen(req, context=self.ctx, timeout=120)
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
                # Missing certificate link: fetch it once and retry.
                _fetch_missing_intermediate(self.host)
                self.ctx = _build_ssl_context(self.host)
                return urllib.request.urlopen(req, context=self.ctx, timeout=120)
            raise

    def _post(self, path, fields):
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(self.base_url + path, data=data)
        return self._open(req).read().decode(errors="replace")

    # -- auth --------------------------------------------------------------
    def login(self, username, password):
        """Exchange username/password for a long-lived access token."""
        body = self._post("/login/token.php", {
            "username": username,
            "password": password,
            "service": "moodle_mobile_app",
        })
        obj = json.loads(body[re.search(r"[\[{]", body).start():])
        if "token" not in obj:
            raise LMSError(obj.get("error", "login failed"))
        self.token = obj["token"]
        return self.token

    def call(self, function, **params):
        """Call one web-service function and return parsed data."""
        if not self.token:
            raise LMSError("not logged in")
        fields = {
            "wstoken": self.token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
        }
        fields.update(params)
        body = self._post("/webservice/rest/server.php", fields)
        m = re.search(r"[\[{]", body)  # server prepends a stray HTML comment
        if not m:
            raise LMSError(f"unexpected reply from {function}: {body[:120]}")
        obj = json.loads(body[m.start():])
        if isinstance(obj, dict) and obj.get("exception"):
            raise LMSError(f"{function}: {obj.get('message', obj.get('errorcode'))}")
        return obj

    # -- helpers -----------------------------------------------------------
    def site_info(self):
        return self.call("core_webservice_get_site_info")

    def my_courses(self, userid):
        return self.call("core_enrol_get_users_courses", userid=userid)

    def course_contents(self, courseid):
        return self.call("core_course_get_contents", courseid=courseid)

    def download(self, fileurl, dest_path, on_bytes=None):
        """Download one file. The token goes on the URL for file downloads.
        on_bytes(done, total) is called as data arrives (total may be 0)."""
        sep = "&" if "?" in fileurl else "?"
        url = f"{fileurl}{sep}token={self.token}"
        req = urllib.request.Request(url)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        tmp = dest_path + ".part"
        with self._open(req) as r, open(tmp, "wb") as out:
            total = int(r.headers.get("Content-Length", 0) or 0)
            done = 0
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if on_bytes:
                    on_bytes(done, total)
        os.replace(tmp, dest_path)
        return dest_path

    def upload_to_draft(self, filepath):
        """Upload a local file to a temporary area and return its id, which
        is what assignment submission needs."""
        import mimetypes, uuid
        filename = os.path.basename(filepath)
        with open(filepath, "rb") as f:
            payload = f.read()
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        boundary = "----lmsgrab" + uuid.uuid4().hex
        body = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file_1"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {ctype}\r\n\r\n".encode(),
            payload, b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        url = f"{self.base_url}/webservice/upload.php?token={self.token}"
        req = urllib.request.Request(url, data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        raw = self._open(req).read().decode(errors="replace")
        obj = json.loads(raw[re.search(r"[\[{]", raw).start():])
        if isinstance(obj, dict) and obj.get("error"):
            raise LMSError(obj["error"])
        return obj[0]["itemid"]
