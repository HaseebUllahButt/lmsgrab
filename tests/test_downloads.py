import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from lmsgrab import cli, engine


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "LMS"
        self.item = {"filename": "lecture.pdf", "size": 4, "time": 2,
                     "fileurl": "https://example.test/lecture.pdf",
                     "rel": "Course/Lectures/01 - lecture.pdf"}
        self.client = Mock()
        self.client.my_courses.return_value = [{"id": 7}]

        def download(url, dest, on_bytes=None):
            Path(dest).write_bytes(b"new!")
        self.client.download.side_effect = download
        self.collect = patch.object(engine, "collect_items", side_effect=lambda *a, **kw: [dict(self.item)])
        self.collect.start()
        self.addCleanup(self.collect.stop)

    def existing_file(self, content=b"old!"):
        path = self.out / self.item["rel"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def download(self, **kw):
        kw.setdefault("scan_dirs", False)
        return engine.smart_download(self.client, [{"id": 7}], str(self.out), **kw)

    def run_cli(self, *args, live=False):
        output = io.StringIO()
        output.isatty = lambda: live
        with patch.object(cli, "_client", return_value=(self.client, {"userid": 42})), \
                patch.object(cli.state, "load_manifest", return_value={}), \
                patch.object(cli.state, "save_manifest") as save, \
                contextlib.redirect_stdout(output):
            cli.main(["download", "--out", str(self.out), "--books", "--no-scan", *args])
        return output.getvalue(), save

    def test_force_fetches_even_when_history_and_local_file_match(self):
        for only_new in (False, True):
            with self.subTest(only_new=only_new):
                target = self.existing_file()
                with patch.object(engine, "scan_existing") as scan:
                    result = self.download(force=True, only_new=only_new, scan_dirs=[self.tmp.name],
                                           manifest={self.item["fileurl"]: 2})
                scan.assert_not_called()
                self.assertEqual(target.read_bytes(), b"new!")
                self.assertEqual(result["downloaded"], 1)

    def test_updated_file_is_refetched_even_if_size_is_unchanged(self):
        target = self.existing_file()
        result = self.download(only_new=True, manifest={self.item["fileurl"]: 1})
        self.assertEqual(target.read_bytes(), b"new!")
        self.assertEqual(result["manifest"][self.item["fileurl"]], 2)

    def test_updated_file_does_not_reuse_stale_copy_from_another_folder(self):
        source = Path(self.tmp.name) / "lecture.pdf"
        source.write_bytes(b"old!")
        result = self.download(manifest={self.item["fileurl"]: 1}, scan_dirs=[self.tmp.name])
        self.assertEqual(result["reused"], 0)
        self.assertEqual((self.out / self.item["rel"]).read_bytes(), b"new!")

    def test_failed_update_keeps_old_history_and_remains_retryable(self):
        target = self.existing_file()
        self.client.download.side_effect = OSError("offline")
        with patch("time.sleep"):
            result = self.download(only_new=True, manifest={self.item["fileurl"]: 1})
        self.assertEqual(target.read_bytes(), b"old!")
        self.assertEqual(result["manifest"][self.item["fileurl"]], 1)
        self.assertEqual(result["files"], [])
        self.assertEqual(result["failed"], 1)
        self.client.download.side_effect = lambda url, dest, **kw: Path(dest).write_bytes(b"new!")
        retry = self.download(only_new=True, manifest=result["manifest"])
        self.assertEqual(retry["downloaded"], 1)
        self.assertEqual(target.read_bytes(), b"new!")

    def test_existing_complete_file_is_counted_and_can_be_zipped(self):
        self.existing_file(b"new!")
        output, _ = self.run_cli("--zip")
        self.client.download.assert_not_called()
        self.assertIn("1 already in place", output)
        self.assertTrue(Path(str(self.out) + ".zip").is_file())

    def test_cli_force_is_connected_to_download_engine(self):
        target = self.existing_file()
        output, _ = self.run_cli("--force")
        self.assertEqual(target.read_bytes(), b"new!")
        self.assertIn("1 downloaded", output)

    def test_terminal_failures_are_visible_and_exit_nonzero(self):
        self.client.download.side_effect = OSError("offline")
        output = io.StringIO()
        output.isatty = lambda: True
        with patch.object(cli, "_client", return_value=(self.client, {"userid": 42})), \
                patch.object(cli.state, "load_manifest", return_value={}), \
                patch.object(cli.state, "save_manifest") as save, \
                patch("time.sleep"), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as error:
                cli.main(["download", "--out", str(self.out), "--books", "--no-scan"])
        self.assertEqual(error.exception.code, 1)
        self.assertIn("FAILED", output.getvalue())
        self.assertIn("offline", output.getvalue())
        self.assertIn("retry", output.getvalue())
        self.assertNotIn("Files are in:", output.getvalue())
        self.assertEqual(save.call_args.args[0], {})

    def test_progress_completes_for_local_files_without_byte_callbacks(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            progress = cli.Progress()
            progress.start(1, 1, "lecture.pdf")
            progress.finish("have")
        self.assertIn("100%", output.getvalue())

    def test_interruption_clears_progress_and_prints_no_traceback(self):
        output = io.StringIO()
        with patch.object(cli, "_client", return_value=(self.client, {"userid": 42})), \
                patch.object(cli.state, "load_manifest", return_value={}), \
                patch.object(engine, "smart_download", side_effect=KeyboardInterrupt), \
                patch.object(cli.Progress, "close") as close, \
                contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as error:
                cli.main(["download", "--books"])
        self.assertIn("Cancelled", str(error.exception))
        close.assert_called_once()

    def test_network_error_is_actionable_without_traceback(self):
        from urllib.error import URLError
        with patch.object(cli, "_client", side_effect=URLError("offline")):
            with self.assertRaises(SystemExit) as error:
                cli.main(["courses"])
        self.assertIn("Check your connection", str(error.exception))


class CommandTests(unittest.TestCase):
    def test_no_command_shows_help(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli.main([])
        self.assertIn("usage: lms", output.getvalue())

    def test_conflicting_download_flags_are_rejected_before_login(self):
        for flags in (["--books", "--no-books"], ["--look", "folder", "--no-scan"]):
            with self.subTest(flags=flags), patch.object(cli, "_client") as client, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    cli.main(["download", *flags])
                self.assertEqual(error.exception.code, 2)
                client.assert_not_called()

    def test_invalid_agent_selection_reprompts_without_wiring_all(self):
        agent_a = {"present": True, "label": "First"}
        agent_b = {"present": True, "label": "Second"}
        with patch("lmsgrab.agents.detect", return_value=[agent_a, agent_b]), \
                patch("lmsgrab.agents.wire", return_value="connected") as wire, \
                patch.object(cli, "_tty_input", side_effect=["1 99", "2", "0"]), \
                patch.object(cli, "_ask_login"), contextlib.redirect_stdout(io.StringIO()):
            cli.main(["start"])
        wire.assert_called_once_with(agent_b)

    def test_agent_setup_can_be_skipped(self):
        with patch("lmsgrab.agents.detect", return_value=[{"present": True, "label": "First"}]), \
                patch("lmsgrab.agents.wire") as wire, \
                patch.object(cli, "_tty_input", return_value="0"), \
                patch.object(cli, "_ask_login") as login, contextlib.redirect_stdout(io.StringIO()):
            cli.main(["start"])
        wire.assert_not_called()
        login.assert_called_once()

    def test_invalid_launch_choice_reprompts_without_repeating_setup(self):
        agent = {"present": True, "label": "First", "kind": "cli", "open": Mock(return_value=True)}
        with patch("lmsgrab.agents.detect", return_value=[agent]), \
                patch("lmsgrab.agents.wire", return_value="connected") as wire, \
                patch.object(cli, "_tty_input", side_effect=["", "99", "1"]), \
                patch.object(cli, "_ask_login"), contextlib.redirect_stdout(io.StringIO()):
            cli.main(["start"])
        wire.assert_called_once()
        agent["open"].assert_called_once()

    def test_submit_expands_home_and_prioritizes_exact_assignment_id(self):
        client = Mock()
        client.call.return_value = {"courses": [{"assignments": [
            {"id": 9, "name": "Final project"}, {"id": 10, "name": "Assignment 9"},
        ]}]}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(cli.os.path, "expanduser", return_value=str(Path(folder, "report.pdf"))) as expand, \
                patch.object(cli, "_client", return_value=(client, {})), \
                contextlib.redirect_stdout(io.StringIO()):
            Path(folder, "report.pdf").write_bytes(b"report")
            cli.main(["submit", "7", "9", "~/report.pdf"])
            expand.assert_called_once_with("~/report.pdf")
            client.upload_to_draft.assert_called_once_with(str(Path(folder, "report.pdf")))
        self.assertEqual(client.call.call_args.kwargs["assignmentid"], 9)


if __name__ == "__main__":
    unittest.main()
