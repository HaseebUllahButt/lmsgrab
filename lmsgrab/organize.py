"""Decides where each file goes inside a course folder, and cleans up names
so they are safe on any computer."""
import html
import re

# Which bucket (sub-folder) does an item belong to? Order matters: the first
# rule that matches wins.
BUCKETS = [
    ("Labs",            re.compile(r"\blab\b|\blab\d|lab\s*\d", re.I)),
    ("Assignments",     re.compile(r"assignment|\bassign\b|\bquiz\b", re.I)),
    ("Course Material", re.compile(r"outline|text\s*book|reference|syllabus|"
                                   r"cormen|thomas|lesson\s*plan|hand\s*book", re.I)),
]


# A file looks like a book/reference if its name says so, or it's a big PDF.
BOOKISH = re.compile(r"text\s*book|reference|cormen|thomas|\bedition\b|"
                     r"pearson|springer|mcgraw|\bvol(ume)?\b|handbook", re.I)
BIG_PDF = 8 * 1024 * 1024  # 8 MB


def is_book(item_name, filename, filesize=0, bucket=None):
    """Best-effort guess: is this a textbook/reference the student may skip?"""
    text = f"{item_name or ''} {filename or ''}"
    if BOOKISH.search(text):
        return True
    if (filename or "").lower().endswith(".pdf") and filesize and filesize >= BIG_PDF:
        return True
    return False


def classify(item_name, section_name, modname):
    """Return the sub-folder name for one course item."""
    name = html.unescape(item_name or "")
    for bucket, rx in BUCKETS:
        if rx.search(name):
            return bucket
    # Things sitting in the course's "General" section are usually the
    # outline / textbooks / admin material.
    if (section_name or "").strip().lower() in ("general", ""):
        return "Course Material"
    # Default: it's teaching material for that week.
    return "Lectures"


_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe(name, default="untitled"):
    """Make a string safe to use as a file or folder name."""
    name = html.unescape(name or "").strip()
    name = _BAD.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    name = name[:150]  # keep paths from getting too long
    return name or default


def course_folder(course):
    """A tidy folder name like 'CS-417 Large Language Model'."""
    short = safe(course.get("shortname", ""))
    full = safe(course.get("fullname", ""))
    # Pull the course code (e.g. CS-417) off the front of the short name.
    m = re.match(r"([A-Z]{2,4}[- ]?\d{2,4})", short)
    code = m.group(1).replace(" ", "-") if m else ""
    # Strip the code and any term junk out of the full name for the title.
    title = re.sub(r"^[A-Z]{2,4}[- ]?\d{2,4}[- ]?", "", full)
    title = re.sub(r"\s*(DE|CDE|Gp[- ]?\d+|&amp;|&|2K\d+|BSCS[-\w]*|Sum[- ]?\d+|"
                   r"[A-Z]'?\d{2})\b.*$", "", title).strip(" -&")
    title = safe(title) or safe(full)
    label = f"{code} {title}".strip()
    return safe(label) or full or short
