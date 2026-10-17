# lmsgrab

A simple way to use the NUST LMS (or any Moodle site).
Log in once, then grab all your lectures neatly sorted, pull only what's
new, or hand in an assignment — without ever opening the website.

No extra software needed, just Python 3. Works as a plain command, or you
can tell your AI agent to run it for you.

## Install (one line)

On Mac or Linux:

```
curl -fsSL https://raw.githubusercontent.com/HaseebUllahButt/lmsgrab/main/install.sh | sh
```

That gives you an `lms` command. No pip, nothing else to install — just Python 3
(which Mac and most Linux already have).

On Windows, use it inside WSL or Git Bash with the same line, or run it straight
with Python: `python -m lmsgrab ...` from a copy of this folder.

## Log in once

```
lms login
```

It asks for the site, your username, and your password. The password is
only used once to get an access key; it is **not** stored.

## Use it (plain commands)

```
lms courses                      # see your courses
lms download                     # download everything, sorted, into Downloads/LMS
lms download --zip               # ...and also make one zip
lms new                          # only what changed since last time
lms download --course 1857       # just one course
lms download --no-books          # skip the big textbooks
lms submit 1854 "Assignment 01" myfile.pdf --final
```

What it does when downloading:
- sorts each course into **Lectures / Labs / Assignments / Course Material**,
- numbers lectures by upload date (`01 - …`, `02 - …`),
- asks whether to include big textbooks,
- notices files you already have in Downloads/Desktop/Documents and reuses
  them instead of downloading again,
- puts the finished set in one **LMS** folder in your Downloads.

## Use it through your AI agent (optional)

If you have an AI agent (Claude Desktop, Claude Code, opencode, Cursor,
Windsurf…), connect it once:

```
lms setup-agent
```

Then fully restart the agent and just ask it, for example:
*"list my courses"*, *"download my new lectures"*, or
*"submit report.pdf to Assignment 01 in Algorithms"*.

### How files are sorted

```
LMS/
  CS-417 Large Language Model/
    Lectures/            lecture slides, notes, books
    Labs/                lab manuals and notebooks
    Assignments/         assignment files
    Course Material/     outline, textbooks, references
  CS-251 Design & Analysis of Algorithms/
    ...
```

`--zip` also packs the whole thing into one `LMS.zip`.

### Submitting

```
python3 -m lmsgrab submit <course-id> <assignment name or id> <file>
```

Without `--final` it just saves a draft you can still change. With `--final`
it hands the work in for grading.
```
