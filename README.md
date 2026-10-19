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

That gives you an `lms` command in every new terminal. No pip, nothing else to install — just Python 3.8+
(Mac and most Linux already have it; on Windows the installer offers to get it).

The installer automatically registers the **LMS MCP server for your user account**
in **Claude Code, Codex (CLI and VS Code extension), OpenCode, Cursor, Antigravity,
and GitHub Copilot (CLI and VS Code)**. It also connects detected Claude Desktop,
Gemini CLI and Windsurf installs. These settings apply across projects, including
when an editor's separate CLI isn't installed. You do not need to run `lms start`
before every chat or configure each repository.

Fully quit and reopen your AI app, accept its LMS server trust prompt if shown,
and start a new chat. Once logged in with `lms login`, just ask:

> Download all my lectures from LMS.

The model receives descriptions of the LMS tools: checking your login, listing
courses, downloading lectures and new material, and submitting assignments.
The app starts the local server on demand; no background service or public port
is needed. Registration is per app and per OS user, not a universal OS registry.

On an interactive install, it also offers the existing guided setup:

1. **Pick your AI apps.** It lists the ones on your computer (Claude Code,
   Codex, OpenCode, Claude Desktop, Gemini CLI, Cursor, Antigravity, Copilot, Windsurf). All are
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
lms download --books             # also grab the big textbooks
lms download --force             # fetch fresh copies, even if already downloaded
lms submit 1854 "Assignment 01" myfile.pdf --final
```

What it does when downloading:
- sorts each course into **Lectures / Labs / Assignments / Course Material**,
- numbers lectures by upload date (`01 - …`, `02 - …`),
- leaves out big textbooks by default (in a terminal it asks first; use
  `--books` to include them, `--no-books` to never ask),
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

### Update or repair an existing installation

Re-run the installer above to update both the command and global AI integrations.
Existing users use **the exact same install command**. Updates keep your saved
login, download history, downloaded lectures and unrelated AI app settings.
They refresh the command and MCP registrations, then finish without repeating
the login/app-selection wizard. Restart your AI apps afterward.

Both installers download and check the new code before replacing the old copy.
If the replacement fails its startup check, the old code is restored. A failed
download leaves the installation alone. If an AI settings file needs repair,
the installer reports it without resetting that file; fix it and rerun the command.

On Linux/macOS, it adds `~/.local/bin` to new bash, zsh, sh and fish terminals.
On Windows, it adds the command folder to your user PATH. Already-open terminals
and editors must be fully restarted to pick up PATH changes. Windows and WSL
are separate environments: install in the one where your agent runs.

MCP entries use the absolute Python and server paths, so editors do not need to
find `lms` on PATH. Existing unrelated settings and servers are kept; modified
settings get a `.lms-backup` copy. JSONC settings are accepted and written back as
JSON, with the original comments retained in that backup. Invalid settings are
reported and left untouched. `lms setup-agent` can be rerun after installing a new
app or creating an editor profile; `--all` includes every supported integration.

For noninteractive installs, set `LMSGRAB_NO_START=1` (PowerShell:
`$env:LMSGRAB_NO_START='1'`). Registration still runs; login and app launch are skipped.

Configuration formats follow the official documentation for
[Claude Code](https://code.claude.com/docs/en/mcp),
[Codex](https://developers.openai.com/learn/docs-mcp),
[OpenCode v1](https://opencode.ai/docs/mcp-servers/) and
[v2](https://dev.opencode.ai/v2/docs/mcp-servers/),
[Cursor](https://cursor.com/docs/mcp),
[Antigravity](https://www.antigravity.google/docs/mcp), and
[Copilot / VS Code](https://code.visualstudio.com/docs/agent-customization/mcp-servers).

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
You can add it when your files are already downloaded, too.

Downloads report how many files were downloaded, reused, already in place,
or failed. If any fail, the command exits with an error and lists the failures.
Run the same command again to retry; failed updates are not marked as downloaded.
`--force` bypasses local copies and the download history, including with `lms new`.

### Submitting

```
python3 -m lmsgrab submit <course-id> <assignment name or id> <file>
```

Without `--final` it just saves a draft you can still change. With `--final`
it hands the work in for grading.
