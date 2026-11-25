"""
tests/test_open_app.py

Tests for:
  1. Bug 1 — Deterministic time/date regex routing, short spoken time/date formatting,
     and voice chat length capping (2 short sentences, num_predict=100).
  2. Bug 2 — Clean environment sanitization, launch fallback order, launch verification
     (distinguishing launcher startup, app process existence, and window visibility),
     and logs/apps.log diagnostics.
  3. Live GUI launch tests for firefox, gnome-calculator, and gnome-terminal from a
     conda-polluted environment. Automatically detects missing apps or unavailable
     display sessions and reports SKIPPED instead of false failures.

Run:
    .venv/bin/python -m unittest -v tests/test_open_app.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.deskpilot.agent.intent_classifier import classify_intent, match_deterministic_intent
from src.deskpilot.agent.response_generator import CHAT_PROMPT, _llm as responder_llm, generate_response
from src.deskpilot.agent.tool_executor import execute_tool
from src.deskpilot.agent.tools import app_tools
from src.deskpilot.agent.tools.app_tools import find_app_processes, launch_app, open_app
from src.deskpilot.agent.tools.system_tools import get_current_time
from src.deskpilot.system.platform_utils import build_clean_env, build_launch_plan


def _has_usable_display_session() -> tuple[bool, str]:
    """Check whether a real Wayland or X11 display socket is reachable."""
    wayland = os.environ.get("WAYLAND_DISPLAY", "").strip()
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if wayland:
        wayland_sock = Path(wayland) if os.path.isabs(wayland) else (Path(xdg_runtime) / wayland if xdg_runtime else None)
        if wayland_sock and wayland_sock.exists():
            return True, f"wayland ({wayland_sock})"

    display = os.environ.get("DISPLAY", "").strip()
    if display.startswith(":"):
        disp_num = display[1:].split(".")[0]
        x11_sock = Path(f"/tmp/.X11-unix/X{disp_num}")
        if x11_sock.exists():
            return True, f"x11 ({display})"

    return False, (
        f"No reachable Wayland/X11 display socket "
        f"(DISPLAY={display!r}, WAYLAND_DISPLAY={wayland!r}, XDG_RUNTIME_DIR={xdg_runtime!r})"
    )


def _app_is_available(app_name: str, clean_env: dict[str, str]) -> tuple[bool, str]:
    """Check whether the target application is genuinely installed/launchable."""
    plan = build_launch_plan(app_name, clean_env)
    if not plan:
        return False, f"'{app_name}' not found in PATH or .desktop directories"

    if app_name.lower() == "firefox":
        # On Ubuntu 23.10+, /usr/bin/firefox is a wrapper requiring /snap/bin/firefox.
        has_snap_bin = os.path.isfile("/snap/bin/firefox") and os.access("/snap/bin/firefox", os.X_OK)
        has_esr = any(c["resolved_path"].endswith("firefox-esr") for c in plan)
        if not (has_snap_bin or has_esr):
            return False, "Firefox snap binary (/snap/bin/firefox) is not accessible in this environment"

    return True, "available"


class TestTimeAndChatFixes(unittest.TestCase):
    """Bug 1: Deterministic time/date routing and voice chat capping."""

    def test_time_queries_bypass_llm(self):
        queries = [
            "what time is it",
            "What's the time?",
            "what is time",
            "alexa, what is time?",
            "tell me the time",
            "current time",
        ]
        with patch("src.deskpilot.agent.intent_classifier._llm") as mock_llm:
            for q in queries:
                res = classify_intent(q)
                self.assertEqual(res["intent"], "tool_use", msg=q)
                self.assertEqual(res["tool_name"], "get_current_time", msg=q)
                self.assertEqual(res["tool_args"], {"mode": "time"}, msg=q)
                self.assertEqual(res["confidence"], 1.0, msg=q)
            mock_llm.invoke.assert_not_called()

    def test_date_queries_bypass_llm(self):
        queries = [
            "what's the date",
            "what day is it",
            "today's date",
            "What is today's date?",
            "alexa, what is the date?",
        ]
        with patch("src.deskpilot.agent.intent_classifier._llm") as mock_llm:
            for q in queries:
                res = classify_intent(q)
                self.assertEqual(res["intent"], "tool_use", msg=q)
                self.assertEqual(res["tool_name"], "get_current_time", msg=q)
                self.assertEqual(res["tool_args"], {"mode": "date"}, msg=q)
            mock_llm.invoke.assert_not_called()

    def test_non_time_definitions_do_not_match_deterministic_rule(self):
        self.assertIsNone(match_deterministic_intent("what is time complexity"))
        self.assertIsNone(match_deterministic_intent("what is time travel"))
        self.assertIsNone(match_deterministic_intent("what is time dilation"))

    def test_get_current_time_short_spoken_output(self):
        time_out = get_current_time.invoke({"mode": "time"})
        self.assertTrue(time_out.startswith("It's "), msg=time_out)
        self.assertRegex(time_out, r"^It's \d{1,2}:\d{2} [AP]M\.$")

        date_out = get_current_time.invoke({"mode": "date"})
        self.assertTrue(date_out.startswith("Today is "), msg=date_out)

    def test_response_generator_voice_caps_and_passthrough(self):
        self.assertEqual(responder_llm.num_predict, 100)
        self.assertIn("at most 2 short sentences", CHAT_PROMPT.lower())

        spoken = generate_response(
            response_type="tool_success",
            tool_name="get_current_time",
            tool_output="It's 9:02 AM.",
        )
        self.assertEqual(spoken, "It's 9:02 AM.")

        fail_spoken = generate_response(
            response_type="tool_failure",
            tool_name="open_app",
            tool_output="I couldn't open firefox.",
        )
        self.assertEqual(fail_spoken, "I couldn't open firefox.")


class TestCleanEnvAndLaunchVerification(unittest.TestCase):
    """Bug 2 unit tests: env sanitization, launch order, and failure verification."""

    def test_build_clean_env_strips_conda_and_preserves_desktop_session(self):
        polluted = {
            "PATH": "/home/u/miniconda3/bin:/home/u/anaconda3/condabin:/home/u/DESKPILOT/.venv/bin:/usr/local/bin:/usr/bin",
            "LD_LIBRARY_PATH": "/home/u/anaconda3/lib:/tmp/bad",
            "LD_PRELOAD": "/tmp/evil.so",
            "PYTHONHOME": "/home/u/anaconda3",
            "PYTHONPATH": "/home/u/DESKPILOT",
            "CONDA_PREFIX": "/home/u/anaconda3",
            "CONDA_DEFAULT_ENV": "base",
            "CONDA_SHLVL": "1",
            "DISPLAY": ":0",
            "WAYLAND_DISPLAY": "wayland-0",
            "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.XYZ",
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "HOME": "/home/u",
        }
        clean, diff = build_clean_env(polluted)

        for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH",
                    "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CONDA_SHLVL"):
            self.assertNotIn(key, clean)

        for kept in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
                     "XDG_CURRENT_DESKTOP", "DBUS_SESSION_BUS_ADDRESS", "HOME"):
            self.assertEqual(clean[kept], polluted[kept])

        path_parts = clean["PATH"].split(os.pathsep)
        self.assertFalse(any("conda" in p.lower() or ".venv" in p.lower() for p in path_parts))
        for req in ("/usr/bin", "/bin", "/usr/local/bin", "/snap/bin"):
            self.assertIn(req, path_parts)

        self.assertIn("LD_LIBRARY_PATH", diff["removed_vars"])
        self.assertIn("CONDA_PREFIX", diff["removed_vars"])
        self.assertEqual(len(diff["removed_path_entries"]), 3)

    def test_launch_app_never_claims_success_on_nonzero_exit_or_missing_process(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "apps.log"
            fake_plan = [
                {
                    "strategy": "app_map",
                    "cmd_parts": ["/usr/bin/firefox"],
                    "resolved_path": "/usr/bin/firefox",
                    "install_type": "snap",
                    "desktop_id": None,
                }
            ]

            fake_proc = MagicMock()
            fake_proc.pid = 99999
            fake_proc.poll.return_value = 1

            def fake_popen(*args, **kwargs):
                stderr_fh = kwargs["stderr"]
                stderr_fh.write("Command '/usr/bin/firefox' requires the firefox snap.\n")
                stderr_fh.flush()
                return fake_proc

            with patch.object(app_tools, "APPS_LOG_PATH", log_file), \
                 patch.object(app_tools, "LAUNCH_VERIFY_INITIAL_DELAY_S", 0.01), \
                 patch.object(app_tools, "LAUNCH_VERIFY_MAX_WAIT_S", 0.02), \
                 patch.object(app_tools, "build_launch_plan", return_value=fake_plan), \
                 patch.object(app_tools, "list_wmctrl_windows", return_value=None), \
                 patch.object(app_tools, "find_app_processes", return_value=[]), \
                 patch("subprocess.Popen", side_effect=fake_popen):
                ok, msg = launch_app("firefox")

            self.assertFalse(ok)
            self.assertEqual(msg, "I couldn't open firefox.")
            log_text = log_file.read_text(encoding="utf-8")
            self.assertIn("exit_code=1", log_text)
            self.assertIn("requires the firefox snap", log_text)

    def test_poll_none_alone_is_not_treated_as_success_without_app_process(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "apps.log"
            fake_plan = [
                {
                    "strategy": "app_map",
                    "cmd_parts": ["/snap/bin/firefox"],
                    "resolved_path": "/snap/bin/firefox",
                    "install_type": "snap",
                    "desktop_id": None,
                }
            ]
            fake_proc = MagicMock()
            fake_proc.pid = 88888
            fake_proc.poll.return_value = None  # launcher still alive, but no app process/window!

            with patch.object(app_tools, "APPS_LOG_PATH", log_file), \
                 patch.object(app_tools, "LAUNCH_VERIFY_INITIAL_DELAY_S", 0.01), \
                 patch.object(app_tools, "LAUNCH_VERIFY_MAX_WAIT_S", 0.02), \
                 patch.object(app_tools, "build_launch_plan", return_value=fake_plan), \
                 patch.object(app_tools, "list_wmctrl_windows", return_value=None), \
                 patch.object(app_tools, "find_app_processes", return_value=[]), \
                 patch("subprocess.Popen", return_value=fake_proc):
                ok, msg = launch_app("firefox")

            self.assertFalse(ok)
            self.assertEqual(msg, "I couldn't open firefox.")

    def test_launcher_exiting_zero_succeeds_when_target_process_verified(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "apps.log"
            fake_plan = [
                {
                    "strategy": "app_map",
                    "cmd_parts": ["/usr/bin/gnome-terminal"],
                    "resolved_path": "/usr/bin/gnome-terminal",
                    "install_type": "apt",
                    "desktop_id": None,
                }
            ]
            fake_proc = MagicMock()
            fake_proc.pid = 77777
            fake_proc.poll.return_value = 0  # forwarded to gnome-terminal-server and exited 0

            with patch.object(app_tools, "APPS_LOG_PATH", log_file), \
                 patch.object(app_tools, "LAUNCH_VERIFY_INITIAL_DELAY_S", 0.01), \
                 patch.object(app_tools, "LAUNCH_VERIFY_MAX_WAIT_S", 0.02), \
                 patch.object(app_tools, "build_launch_plan", return_value=fake_plan), \
                 patch.object(app_tools, "list_wmctrl_windows", return_value=None), \
                 patch.object(app_tools, "find_app_processes", side_effect=[[], [4321]]), \
                 patch("subprocess.Popen", return_value=fake_proc):
                ok, msg = launch_app("gnome-terminal")

            self.assertTrue(ok)
            self.assertEqual(msg, "Opened gnome-terminal successfully.")

    def test_execute_tool_propagates_open_app_failure(self):
        with patch("src.deskpilot.agent.tool_executor.launch_app", return_value=(False, "I couldn't open firefox.")):
            ok, msg = execute_tool("open_app", {"app_name": "firefox"})
        self.assertFalse(ok)
        self.assertEqual(msg, "I couldn't open firefox.")


class TestOpenAppLiveGUI(unittest.TestCase):
    """
    Live GUI tests launching firefox, gnome-calculator, and gnome-terminal
    through open_app from a conda-polluted environment.
    Reports SKIPPED if display session or target app is unavailable.
    """

    def setUp(self):
        has_disp, disp_reason = _has_usable_display_session()
        if not has_disp:
            self.skipTest(f"SKIPPED: {disp_reason}")
        self.clean_env, _ = build_clean_env()
        self.spawned_to_cleanup: list[int] = []

    def tearDown(self):
        import psutil
        for pid in self.spawned_to_cleanup:
            try:
                psutil.Process(pid).terminate()
            except Exception:
                pass

    def _run_conda_polluted_launch(self, app_name: str):
        available, reason = _app_is_available(app_name, self.clean_env)
        if not available:
            self.skipTest(f"SKIPPED: {reason}")

        before_pids = set(find_app_processes(app_name, [app_name], "apt", self.clean_env))
        polluted_updates = {
            "LD_LIBRARY_PATH": "/tmp/fake_conda_env/lib:/opt/conda/lib",
            "LD_PRELOAD": "/tmp/nonexistent_preload.so",
            "CONDA_PREFIX": "/opt/conda",
            "CONDA_DEFAULT_ENV": "base",
            "PATH": f"/opt/conda/bin:{PROJECT_ROOT / '.venv/bin'}:{os.environ.get('PATH', '')}",
        }
        with patch.dict(os.environ, polluted_updates):
            result = open_app.invoke({"app_name": app_name})

        self.assertTrue(
            result.startswith("Opened ") and "successfully" in result,
            msg=f"Expected success for {app_name}, got: {result}",
        )

        after_pids = set(find_app_processes(app_name, [app_name], "apt", self.clean_env))
        self.assertTrue(len(after_pids) > 0, msg=f"No running process found for {app_name}")
        self.spawned_to_cleanup.extend(sorted(after_pids - before_pids))

    def test_launch_firefox_from_conda_env(self):
        self._run_conda_polluted_launch("firefox")

    def test_launch_gnome_calculator_from_conda_env(self):
        self._run_conda_polluted_launch("gnome-calculator")

    def test_launch_gnome_terminal_from_conda_env(self):
        self._run_conda_polluted_launch("gnome-terminal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
