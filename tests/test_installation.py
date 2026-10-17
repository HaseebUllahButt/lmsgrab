import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from lmsgrab import agents, install, update


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lms user's home ")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home),
               "XDG_CONFIG_HOME": str(self.home / ".config"),
               "CODEX_HOME": str(self.home / ".codex"),
               "COPILOT_HOME": str(self.home / ".copilot"),
               "APPDATA": str(self.home / "AppData/Roaming"),
               "ZDOTDIR": str(self.home)}
        self.env = patch.dict(os.environ, env)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_all_priority_apps_registered_without_any_cli(self):
        with patch.object(agents.shutil, "which", return_value=None):
            messages = agents.setup()
        self.assertFalse(any("couldn't" in m for m in messages), messages)
        for agent in agents.detect():
            if agent["key"] not in agents.PRIORITY:
                continue
            self.assertTrue(Path(agent["config"]).is_file(), agent["key"])
            if agent["shape"] != "codex":
                data = json.loads(Path(agent["config"]).read_text())
                group = "mcp" if agent["shape"] == "opencode" else "servers" if agent["shape"] == "vscode" else "mcpServers"
                servers = data[group].get("servers", data[group]) if agent["shape"] == "opencode" else data[group]
                entry = servers["lms"]
                cmd = entry["command"]
                self.assertEqual(cmd[0] if isinstance(cmd, list) else cmd, sys.executable)

    def test_codex_extension_without_cli_is_detected(self):
        (self.home / ".vscode/extensions/openai.chatgpt-1.0").mkdir(parents=True)
        with patch.object(agents.shutil, "which", return_value=None):
            codex = next(a for a in agents.detect() if a["key"] == "codex")
        self.assertTrue(codex["present"])
        self.assertEqual(codex["kind"], "gui")

    def test_codex_update_preserves_other_tables_and_multiline_strings(self):
        import tomllib
        config = self.home / "config.toml"
        original = ('instructions = """example:\n[mcp_servers.lms]\nkeep this\n"""\n'
                    '[mcp_servers."lms"]\ncommand = "old"\n'
                    '[mcp_servers.lms.env]\nOLD = "remove"\n'
                    '[mcp_servers.other]\ncommand = "other"\n'
                    '[projects."/my/project"]\ntrust_level = "trusted"\n')
        config.write_text(original)
        exe = r"C:\Users\Student Name\Python\python.exe"
        args = [r"C:\Users\Student Name\LMS\run_mcp.py"]
        agents._wire_codex(str(config), exe, args)
        first = config.read_text()
        agents._wire_codex(str(config), exe, args)
        self.assertEqual(first, config.read_text())
        data = tomllib.loads(first)
        self.assertEqual(data["instructions"], tomllib.loads(original)["instructions"])
        self.assertEqual(data["mcp_servers"]["other"], {"command": "other"})
        self.assertEqual(data["mcp_servers"]["lms"]["command"], exe)
        self.assertEqual(data["mcp_servers"]["lms"]["args"], args)
        self.assertNotIn("env", data["mcp_servers"]["lms"])
        self.assertEqual(Path(str(config) + ".lms-backup").read_text(), original)

    def test_invalid_configs_are_not_overwritten(self):
        path = self.home / "config"
        for shape in ("codex", "mcpServers", "vscode", "opencode"):
            path.write_text("{broken settings")
            result = agents.wire({"shape": shape, "label": "Test", "config": str(path)})
            self.assertIn("couldn't connect", result)
            self.assertEqual(path.read_text(), "{broken settings")

    def test_jsonc_settings_and_existing_servers_survive_repeat_setup(self):
        path = self.home / ".config/opencode/opencode.jsonc"
        path.parent.mkdir(parents=True)
        original = '{// config\n"model":"keep", "mcp":{"other":{"url":"https://example.test/a//b",},},}'
        path.write_text(original)
        self.assertEqual(agents._opencode_config(), str(path))
        with patch.object(agents, "_opencode_v2", return_value=False):
            agents._wire_json(str(path), "opencode", sys.executable, ["server.py"])
            first = path.read_text()
            agents._wire_json(str(path), "opencode", sys.executable, ["server.py"])
        self.assertEqual(first, path.read_text())
        data = json.loads(first)
        self.assertEqual(data["model"], "keep")
        self.assertEqual(data["mcp"]["other"]["url"], "https://example.test/a//b")
        self.assertEqual(Path(str(path) + ".lms-backup").read_text(), original)

    def test_opencode_v2_uses_nested_servers_and_removes_stale_lms_entry(self):
        path = self.home / "opencode.json"
        path.write_text(json.dumps({"mcp": {"lms": {"command": ["old"]},
                                          "servers": {"keep": {"type": "remote", "url": "https://example.test"}}}}))
        with patch.object(agents, "_opencode_v2", return_value=True):
            agents._wire_json(str(path), "opencode", sys.executable, ["server.py"])
        mcp = json.loads(path.read_text())["mcp"]
        self.assertNotIn("lms", mcp)
        self.assertIn("keep", mcp["servers"])
        self.assertEqual(mcp["servers"]["lms"]["command"], [sys.executable, "server.py"])
        self.assertNotIn("enabled", mcp["servers"]["lms"])

    def test_empty_antigravity_config_is_initialized(self):
        path = self.home / "mcp_config.json"
        path.touch()
        agents._wire_json(str(path), "mcpServers", sys.executable, ["server.py"])
        self.assertIn("lms", json.loads(path.read_text())["mcpServers"])

    def test_windows_config_locations_and_vscode_profiles(self):
        with patch.object(agents, "WINDOWS", True):
            root = self.home / "AppData/Roaming/Code/User"
            profile = root / "profiles/school"
            profile.mkdir(parents=True)
            paths = agents._vscode_paths()
            self.assertIn(str(root / "mcp.json"), paths)
            self.assertIn(str(profile / "mcp.json"), paths)

    @unittest.skipIf(os.name == "nt", "POSIX shell launchers")
    def test_full_shell_installer_uses_installed_copy_even_from_source_folder(self):
        repo = Path(__file__).resolve().parents[1]
        archive = self.home / "source.tgz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(repo / "lmsgrab", arcname="lmsgrab-main/lmsgrab")
        fakebin = self.home / "fakebin"
        fakebin.mkdir()
        curl = fakebin / "curl"
        curl.write_text('#!/bin/sh\ncp "$LMS_TEST_ARCHIVE" "$4"\n')
        curl.chmod(0o755)
        env = dict(os.environ, PATH=str(fakebin) + ":/usr/bin:/bin",
                   XDG_DATA_HOME=str(self.home / ".local/share"),
                   LMS_TEST_ARCHIVE=str(archive), LMSGRAB_NO_START="1")
        result = subprocess.run(["sh", str(repo / "install.sh")], cwd=repo, env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        config = json.loads((self.home / ".cursor/mcp.json").read_text())
        runner = config["mcpServers"]["lms"]["args"][0]
        self.assertEqual(Path(runner).resolve(), (self.home / ".local/share/lmsgrab/lmsgrab/run_mcp.py").resolve())
        result = subprocess.run([str(self.home / ".local/bin/lms"), "--help"],
                                cwd=self.home, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

        # A second invocation updates in place without onboarding, including
        # when users keep their login, history, lectures and other MCP servers.
        saved = self.home / ".config/lmsgrab"
        saved.mkdir(parents=True)
        (saved / "config.json").write_text('{"token":"saved-test-token"}')
        (saved / "manifest.json").write_text('{"lecture":123}')
        lecture = self.home / "Downloads/LMS/lecture.pdf"
        lecture.parent.mkdir(parents=True)
        lecture.write_bytes(b"my lecture")
        cursor_config = self.home / ".cursor/mcp.json"
        data = json.loads(cursor_config.read_text())
        data["mcpServers"]["other"] = {"command": "keep-me"}
        cursor_config.write_text(json.dumps(data))
        profile = (self.home / ".profile").read_text()
        old_module = Path(runner).parent / "obsolete.py"
        old_module.write_text("# removed by the next release")
        env.pop("LMSGRAB_NO_START")
        result = subprocess.run(["sh", str(repo / "install.sh")], cwd=repo, env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Update complete", result.stdout)
        self.assertNotIn("All set. To begin", result.stdout)
        self.assertEqual((saved / "config.json").read_text(), '{"token":"saved-test-token"}')
        self.assertEqual((saved / "manifest.json").read_text(), '{"lecture":123}')
        self.assertEqual(lecture.read_bytes(), b"my lecture")
        self.assertEqual((self.home / ".profile").read_text(), profile)
        self.assertEqual(json.loads(cursor_config.read_text())["mcpServers"]["other"], {"command": "keep-me"})
        self.assertFalse(old_module.exists())

        # A network failure must leave the installed command working.
        curl.write_text('#!/bin/sh\nexit 22\n')
        result = subprocess.run(["sh", str(repo / "install.sh")], cwd=repo, env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        result = subprocess.run([str(self.home / ".local/bin/lms"), "--help"],
                                cwd=self.home, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_update_keeps_previous_code(self):
        source = self.home / "download"
        shutil.copytree(Path(update.__file__).parent, source)
        (source / "cli.py").write_text("def broken(")
        app = self.home / "app"
        target = app / "lmsgrab"
        target.mkdir(parents=True)
        (target / "old.py").write_text("previous code")
        with self.assertRaises(SyntaxError):
            update.update_package(source, app)
        self.assertEqual((target / "old.py").read_text(), "previous code")
        self.assertEqual(list(app.iterdir()), [target])

    def test_failed_post_install_check_restores_previous_code(self):
        app = self.home / "app"
        target = app / "lmsgrab"
        target.mkdir(parents=True)
        (target / "old.py").write_text("previous code")
        with patch.object(update, "check_package", side_effect=[None, RuntimeError("startup failed")]):
            with self.assertRaisesRegex(RuntimeError, "startup failed"):
                update.update_package(Path(update.__file__).parent, app)
        self.assertEqual((target / "old.py").read_text(), "previous code")
        self.assertEqual(list(app.iterdir()), [target])

    @unittest.skipIf(os.name == "nt", "POSIX shell launchers")
    def test_fresh_shell_finds_command_and_mcp_runs_outside_repo(self):
        bindir = self.home / ".local/bin"
        install.install_commands(bindir)
        install.install_path(bindir)
        before = (self.home / ".bashrc").read_text()
        install.install_path(bindir)
        self.assertEqual(before, (self.home / ".bashrc").read_text())
        env = dict(os.environ, PATH="/usr/bin:/bin")
        env.pop("PYTHONPATH", None)
        result = subprocess.run(["sh", "-c", '. "$HOME/.profile"; lms --help'],
                                cwd=self.home, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: lms", result.stdout)
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "whoami"}},
        ]
        result = subprocess.run([str(bindir / "lms-mcp")], cwd=self.home, env=env,
                                input="\n".join(map(json.dumps, requests)) + "\n",
                                capture_output=True, text=True, timeout=10)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(replies), 3)
        self.assertIn("download_lectures", [t["name"] for t in replies[1]["result"]["tools"]])
        self.assertIn("Not logged in", replies[2]["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
