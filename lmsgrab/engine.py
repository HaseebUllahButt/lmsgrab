"""The shared core: walk a course's files, download them sorted, build a zip.
Both the command tool and the website use this."""
import os
import zipfile

from . import organize

SKIP_MODS = {"forum", "label", "enhancedlabel", "page", "url", "lti", "quiz", "feedback"}


def walk_files(client, course):
    """Yield (relative_path, file_dict) for every downloadable file in a course."""
    folder = organize.course_folder(course)
    for sec in client.course_contents(course["id"]):
        sname = sec.get("name", "")
        for mod in sec.get("modules", []):
            if mod.get("modname") in SKIP_MODS:
                continue
            files = [c for c in mod.get("contents", [])
                     if c.get("type") == "file" and c.get("fileurl")]
            if not files:
                continue
            bucket = organize.classify(mod.get("name", ""), sname, mod.get("modname"))
            multi = len(files) > 1
            modfolder = organize.safe(mod.get("name", ""))
            for fc in files:
                fname = organize.safe(fc.get("filename", "file"))
                parts = [folder, bucket]
                if multi:
                    parts.append(modfolder)
                sub = (fc.get("filepath") or "/").strip("/")
                if sub:
                    parts.append(organize.safe(sub))
                parts.append(fname)
                yield os.path.join(*parts), fc


def file_key(fc):
    return fc.get("fileurl", "")


def download_courses(client, courses, out_dir, manifest=None, only_new=False,
                     force=False, on_file=None):
    """Download files from the given courses into out_dir, sorted.

    manifest: dict of fileurl -> timemodified from a previous run.
    only_new: skip files whose timestamp matches the manifest.
    Returns (list_of_relative_paths_fetched, skipped_count, new_manifest).
    """
    manifest = manifest or {}
    new_manifest = dict(manifest)
    grabbed, skipped = [], 0
    for c in courses:
        for rel, fc in walk_files(client, c):
            key = file_key(fc)
            stamp = fc.get("timemodified", 0)
            if only_new and manifest.get(key) == stamp:
                skipped += 1
                continue
            dest = os.path.join(out_dir, rel)
            if os.path.exists(dest) and not force and not only_new:
                skipped += 1
            else:
                try:
                    client.download(fc["fileurl"], dest)
                    grabbed.append(rel)
                    if on_file:
                        on_file(rel)
                except Exception as e:
                    if on_file:
                        on_file(f"FAILED {rel}: {e}")
                    continue
            new_manifest[key] = stamp
    return grabbed, skipped, new_manifest


def collect_items(client, courses, include_books=True):
    """Build the full list of files to gather, with upload time and a book
    flag, and number them by upload date within each course+bucket."""
    items = []
    for c in courses:
        cfolder = organize.course_folder(c)
        for sec in client.course_contents(c["id"]):
            sname = sec.get("name", "")
            for mod in sec.get("modules", []):
                if mod.get("modname") in SKIP_MODS:
                    continue
                files = [f for f in mod.get("contents", [])
                         if f.get("type") == "file" and f.get("fileurl")]
                if not files:
                    continue
                bucket = organize.classify(mod.get("name", ""), sname, mod.get("modname"))
                multi = len(files) > 1
                modfolder = organize.safe(mod.get("name", "")) if multi else ""
                for fc in files:
                    fname = organize.safe(fc.get("filename", "file"))
                    book = organize.is_book(mod.get("name", ""), fc.get("filename", ""),
                                            fc.get("filesize", 0), bucket)
                    if book and not include_books:
                        continue
                    items.append({
                        "course": cfolder, "bucket": bucket, "modfolder": modfolder,
                        "filename": fname, "fileurl": fc["fileurl"],
                        "size": fc.get("filesize", 0),
                        "time": fc.get("timemodified", 0) or fc.get("timecreated", 0),
                        "book": book,
                    })
    _number(items)
    return items


def _number(items):
    """Prefix lecture-type files with 01 -, 02 - ... in upload order, so they
    read in the order the teacher posted them."""
    groups = {}
    for it in items:
        groups.setdefault((it["course"], it["bucket"]), []).append(it)
    for (course, bucket), group in groups.items():
        if bucket not in ("Lectures", "Labs"):
            # Books/outlines/assignments: leave names alone.
            for it in group:
                it["rel"] = _rel(it, it["filename"])
            continue
        group.sort(key=lambda x: (x["time"], x["filename"]))
        width = max(2, len(str(len(group))))
        for i, it in enumerate(group, 1):
            name = it["filename"]
            if it["modfolder"]:
                it["rel"] = _rel(it, name)  # files inside a module folder keep their name
            else:
                it["rel"] = _rel(it, f"{str(i).zfill(width)} - {name}")


def _rel(it, filename):
    parts = [it["course"], it["bucket"]]
    if it["modfolder"]:
        parts.append(it["modfolder"])
    parts.append(filename)
    return os.path.join(*parts)


def scan_existing(wanted, search_dirs, max_depth=3):
    """Look for files you already downloaded. Match by name + size so we can
    skip re-downloading them. Returns {(name,size): fullpath}."""
    want = {(w["filename"], w["size"]) for w in wanted}
    want_names = {w["filename"] for w in wanted}
    found = {}
    for base in search_dirs:
        base = os.path.expanduser(base)
        if not os.path.isdir(base):
            continue
        baredepth = base.rstrip("/").count("/")
        for root, dirs, files in os.walk(base):
            if root.count("/") - baredepth > max_depth:
                dirs[:] = []
                continue
            for fn in files:
                if fn not in want_names:
                    continue
                full = os.path.join(root, fn)
                try:
                    sz = os.path.getsize(full)
                except OSError:
                    continue
                if (fn, sz) in want and (fn, sz) not in found:
                    found[(fn, sz)] = full
    return found


def assemble(client, items, dest, existing=None, move=False, on_file=None,
             progress=None):
    """Put every item into dest: copy from an already-downloaded copy when we
    found one, otherwise download it. Returns (downloaded, reused, failed).

    progress is an optional object with .start(i, total, name), .bytes(done,
    total) and .finish(status) methods for a live progress bar."""
    import shutil, time
    existing = existing or {}
    total = len(items)
    downloaded = reused = failed = skipped = 0
    for i, it in enumerate(items, 1):
        target = os.path.join(dest, it["rel"])
        os.makedirs(os.path.dirname(target), exist_ok=True)
        have = existing.get((it["filename"], it["size"]))
        name = os.path.basename(it["rel"])
        if progress:
            progress.start(i, total, name)
        # Resume: if we already have a complete copy here, don't fetch it again.
        if (os.path.exists(target) and it["size"]
                and os.path.getsize(target) == it["size"]):
            skipped += 1
            if progress:
                progress.finish("have")
            continue
        try:
            if have and os.path.exists(have) and os.path.abspath(have) != os.path.abspath(target):
                shutil.move(have, target) if move else shutil.copy2(have, target)
                reused += 1
                status = "reused"
            else:
                # Retry a few times — the school server drops connections.
                last = None
                for attempt in range(3):
                    try:
                        client.download(it["fileurl"], target,
                                        on_bytes=(progress.bytes if progress else None))
                        last = None
                        break
                    except Exception as e:
                        last = e
                        time.sleep(1.5 * (attempt + 1))
                if last:
                    raise last
                downloaded += 1
                status = "got"
            if on_file:
                on_file(f"{status}  {it['rel']}")
            if progress:
                progress.finish(status)
        except Exception as e:
            failed += 1
            if on_file:
                on_file(f"FAILED  {it['rel']}: {e}")
            if progress:
                progress.finish("failed")
    return downloaded, reused, failed


DEFAULT_SCAN = ["~/Downloads", "~/Desktop", "~/Documents"]


def smart_download(client, courses, out, include_books=True, only_new=False,
                   manifest=None, scan_dirs=None, move=False, on_file=None,
                   progress=None):
    """The whole smart flow in one call, shared by the command tool and the AI
    agent: list files, (optionally) skip books, skip unchanged, reuse files the
    student already has, download the rest, number and sort into `out`.

    Returns a summary dict (and an updated manifest under 'manifest')."""
    manifest = dict(manifest or {})
    items = collect_items(client, courses, include_books=include_books)
    if only_new:
        items = [it for it in items if manifest.get(it["fileurl"]) != it["time"]]
    existing = {}
    if scan_dirs is not False:
        existing = scan_existing(items, scan_dirs or DEFAULT_SCAN)
    if items:
        os.makedirs(out, exist_ok=True)
    got, reused, failed = assemble(client, items, out, existing=existing,
                                   move=move, on_file=on_file, progress=progress)
    # Tidy up any half-finished downloads left by an earlier interrupted run.
    for root, _, files in os.walk(out):
        for fn in files:
            if fn.endswith(".part"):
                try:
                    os.remove(os.path.join(root, fn))
                except OSError:
                    pass
    # Only remember files that actually made it (so a failed one retries next time).
    for it in items:
        if os.path.exists(os.path.join(out, it["rel"])):
            manifest[it["fileurl"]] = it["time"]
    return {"downloaded": got, "reused": reused, "failed": failed,
            "total": len(items), "out": out, "manifest": manifest,
            "files": [it["rel"] for it in items]}


def make_zip(src_dir, zip_path):
    """Pack everything in src_dir into a single zip file."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(src_dir):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, src_dir))
    return zip_path
