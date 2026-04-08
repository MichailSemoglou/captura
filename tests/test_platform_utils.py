"""
tests/test_platform_utils.py — Unit tests for platform_utils.py
================================================================
Tests to implement (plan.md T-08):

  PU-01  has_screen_recording_permission()    Returns True when mss.grab succeeds
  PU-02  has_screen_recording_permission()    Returns False when mss.grab raises any exception
  PU-03  open_folder()                        Calls subprocess.run(["open", path_str])
  PU-04  open_folder()                        Does not raise when subprocess call succeeds
  PU-05  open_folder()                        Logs to stderr; does NOT re-raise on CalledProcessError
  PU-06  prompt_screen_recording_permission() Calls subprocess.run(["open", PREFS_URL])

Mocking strategy:
  Use mocker.patch() (pytest-mock) to mock:
    - mss.mss              — prevent real screen capture attempts
    - subprocess.run       — prevent real process spawning

  All tests run without a display, real screen access, or macOS system calls.

Run:
  pytest tests/test_platform_utils.py -v
  pytest tests/test_platform_utils.py -v --cov=platform_utils --cov-report=term-missing
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import platform_utils
from platform_utils import SCREEN_RECORDING_PREFS_URL

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _mock_mss(mocker, grab_raises: Exception | None = None) -> MagicMock:
    """Patch ``mss.mss`` and optionally make ``grab`` raise *grab_raises*."""
    mock_sct = MagicMock()
    mock_sct.__enter__ = MagicMock(return_value=mock_sct)
    mock_sct.__exit__ = MagicMock(return_value=False)
    if grab_raises is not None:
        mock_sct.grab.side_effect = grab_raises
    mocker.patch("mss.mss", return_value=mock_sct)
    return mock_sct


# ---------------------------------------------------------------------------
# has_screen_recording_permission() — PU-01, PU-02
# ---------------------------------------------------------------------------

def test_pu01_has_permission_returns_true_when_grab_succeeds(mocker):
    """PU-01: has_screen_recording_permission() returns True when mss.grab succeeds."""
    _mock_mss(mocker)
    assert platform_utils.has_screen_recording_permission() is True


def test_pu02_has_permission_returns_false_when_grab_raises(mocker):
    """PU-02: has_screen_recording_permission() returns False when grab raises."""
    _mock_mss(mocker, grab_raises=Exception("permission denied"))
    assert platform_utils.has_screen_recording_permission() is False


# ---------------------------------------------------------------------------
# open_folder() — PU-03, PU-04, PU-05
# ---------------------------------------------------------------------------

def test_pu03_open_folder_calls_subprocess_run_with_open(mocker, tmp_path):
    """PU-03: open_folder() calls subprocess.run(["open", str(path)], check=True)."""
    mock_run = mocker.patch("subprocess.run")
    platform_utils.open_folder(tmp_path)
    mock_run.assert_called_once_with(["open", str(tmp_path)], check=True)


def test_pu04_open_folder_does_not_raise_on_success(mocker, tmp_path):
    """PU-04: open_folder() does not raise when subprocess.run succeeds."""
    mocker.patch("subprocess.run")
    platform_utils.open_folder(tmp_path)  # must not raise


def test_pu05_open_folder_logs_not_raises_on_called_process_error(mocker, tmp_path):
    """PU-05: open_folder() logs to stderr and does NOT re-raise CalledProcessError."""
    mocker.patch(
        "subprocess.run",
        side_effect=subprocess.CalledProcessError(1, ["open", str(tmp_path)]),
    )
    mock_log = mocker.patch("platform_utils.logging.error")

    platform_utils.open_folder(tmp_path)  # must NOT raise

    mock_log.assert_called_once()


# ---------------------------------------------------------------------------
# prompt_screen_recording_permission() — PU-06
# ---------------------------------------------------------------------------

def test_pu06_prompt_permission_opens_prefs_url(mocker):
    """PU-06: prompt_screen_recording_permission() opens the prefs URL via subprocess."""
    mock_run = mocker.patch("subprocess.run")
    platform_utils.prompt_screen_recording_permission()
    mock_run.assert_called_once_with(["open", SCREEN_RECORDING_PREFS_URL], check=True)

