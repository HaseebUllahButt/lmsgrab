# lmsgrab

A simple way to use the NUST LMS (or any Moodle site).
Log in once, then grab all your lectures neatly sorted, pull only what's
new, or hand in an assignment — without ever opening the website.

No extra software needed, just Python 3. Works as a plain command, or you
can tell your AI agent to run it for you.

## Install (one line)

On Mac or Linux, in a terminal:

```
curl -fsSL https://raw.githubusercontent.com/HaseebUllahButt/lmsgrab/main/install.sh | sh
```

On Windows, in PowerShell:

```
irm https://raw.githubusercontent.com/HaseebUllahButt/lmsgrab/main/install.ps1 | iex
```

That gives you an `lms` command. No pip, nothing else to install — just Python 3
(Mac and most Linux already have it; on Windows the installer offers to get it).

Right after installing, it walks you through three quick steps:

1. **Pick your AI apps.** It lists the ones on your computer (Claude Code,
   Codex, OpenCode, Claude Desktop, Gemini CLI, Cursor, Windsurf). All are
   picked; press Enter, or type just the numbers you want.
2. **Log in.** Your LMS username and password, same as the website.
3. **Pick one to open.** Claude Code, Codex and OpenCode come first. It opens
   already knowing what to do: it lists your courses and asks what you want.

You can run these steps again any time with `lms start`.

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

## Easiest: chat with your AI agent

Run:

```
lms start
```

It connects the LMS tool to your AI apps, logs you in, and opens the one you
pick. Then you just talk to it:
*"download my new lectures"*, *"what's new in Algorithms?"*,
*"submit report.pdf to Assignment 01"*.

To connect agents without opening one, use `lms setup-agent`.

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
