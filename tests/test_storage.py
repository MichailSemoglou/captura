"""
tests/test_storage.py — Unit tests for storage.py
==================================================
Tests to implement (plan.md T-02):

  S-01  generate_filename()    Returns correct format for a known datetime + mode
  S-02  generate_filename()    Month, day, hour, minute, second are zero-padded
  S-03  get_screenshots_dir()  Returns ~/Screenshots/ as a pathlib.Path
  S-04  get_screenshots_dir()  Creates the directory if it is absent (mock mkdir)
  S-05  save_image()           Calls image.save() with the correct full path
  S-06  save_image()           Returns the full pathlib.Path of the saved file
  S-07  save_image()           Raises StorageError when image.save() raises OSError
  S-08  save_image()           Raises StorageError when the save dir is a file

Mocking strategy:
  Use mocker.patch() (pytest-mock) to mock:
    - pathlib.Path.mkdir      — prevent real filesystem writes
    - pathlib.Path.is_file    — control the "dir is a file" scenario
    - pathlib.Path.exists     — control the duplicate-filename scenario
    - PIL.Image.Image.save    — prevent real file writes; simulate OSError

  No real files are written to disk during testing.

Run:
  pytest tests/test_storage.py -v
  pytest tests/test_storage.py -v --cov=storage --cov-report=term-missing
"""

from __future__ import annotations

import pathlib
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from PIL import Image

import storage
from storage import StorageError

# ---------------------------------------------------------------------------
# generate_filename() — S-01 and S-02
# ---------------------------------------------------------------------------

def test_s01_generate_filename_correct_format():
    """S-01: generate_filename() returns the expected format for a known datetime and mode."""
    dt = datetime(2026, 4, 5, 14, 30, 45)
    result = storage.generate_filename(dt, "fullscreen")
    assert result == "screenshot_2026-04-05_14-30-45_fullscreen.png"


def test_s02_generate_filename_zero_pads_all_components():
    """S-02: generate_filename() zero-pads month, day, hour, minute, and second."""
    dt = datetime(2026, 1, 2, 3, 4, 5)
    result = storage.generate_filename(dt, "16x9")
    assert result == "screenshot_2026-01-02_03-04-05_16x9.png"


# ---------------------------------------------------------------------------
# get_screenshots_dir() — S-03 and S-04
# ---------------------------------------------------------------------------

def test_s03_get_screenshots_dir_returns_correct_path(monkeypatch, tmp_path):
    """S-03: get_screenshots_dir() returns ~/Screenshots as a pathlib.Path."""
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))

    result = storage.get_screenshots_dir()

    assert result == tmp_path / "Screenshots"
    assert isinstance(result, pathlib.Path)
    assert result.exists()


def test_s04_get_screenshots_dir_creates_directory_when_absent(mocker):
    """S-04: get_screenshots_dir() calls mkdir(parents=True, exist_ok=True)."""
    mocker.patch("pathlib.Path.is_file", return_value=False)
    mock_mkdir = mocker.patch("pathlib.Path.mkdir")

    storage.get_screenshots_dir()

    mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# save_image() — S-05 through S-08
# ---------------------------------------------------------------------------

def test_s05_save_image_calls_save_with_correct_path(mocker, tmp_path):
    """S-05: save_image() atomically creates the correct path and passes it to image.save."""
    mocker.patch("pathlib.Path.is_file", return_value=False)
    fake_fd = 99
    fake_fp = MagicMock()
    fake_fp.__enter__ = MagicMock(return_value=fake_fp)
    fake_fp.__exit__ = MagicMock(return_value=False)
    mock_os_open = mocker.patch("storage.os.open", return_value=fake_fd)
    mocker.patch("storage.os.fdopen", return_value=fake_fp)
    img = MagicMock(spec=Image.Image)
    filename = "screenshot_2026-04-05_14-30-45_fullscreen.png"

    storage.save_image(img, tmp_path, filename)

    import os
    mock_os_open.assert_called_once_with(
        tmp_path / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666
    )
    img.save.assert_called_once_with(fake_fp, format="PNG")


def test_s06_save_image_returns_full_path(mocker, tmp_path):
    """S-06: save_image() returns the full pathlib.Path of the saved file."""
    mocker.patch("pathlib.Path.is_file", return_value=False)
    img = MagicMock(spec=Image.Image)
    filename = "screenshot_2026-04-05_14-30-45_fullscreen.png"

    result = storage.save_image(img, tmp_path, filename)

    assert result == tmp_path / filename
    assert isinstance(result, pathlib.Path)


def test_s07_save_image_raises_storage_error_on_os_error(mocker, tmp_path):
    """S-07: save_image() wraps OSError from image.save() as StorageError."""
    mocker.patch("pathlib.Path.is_file", return_value=False)
    img = MagicMock(spec=Image.Image)
    img.save.side_effect = OSError("no space left on device")

    with pytest.raises(StorageError, match="no space left on device"):
        storage.save_image(img, tmp_path, "screenshot_2026-04-05_14-30-45_custom.png")


def test_s08_save_image_raises_when_directory_is_a_file(mocker, tmp_path):
    """S-08: save_image() raises StorageError when the target directory is a file."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    img = MagicMock(spec=Image.Image)

    with pytest.raises(StorageError):
        storage.save_image(img, tmp_path, "screenshot_2026-04-05_14-30-45_fullscreen.png")


def test_s09_get_screenshots_dir_raises_when_path_is_a_file(mocker):
    """S-09: get_screenshots_dir() raises StorageError when ~/Screenshots is a file."""
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.mkdir")

    with pytest.raises(StorageError, match="already exists as a file"):
        storage.get_screenshots_dir()


def test_s10_save_image_appends_counter_suffix_for_duplicate(mocker, tmp_path):
    """S-10: save_image() appends _1 suffix when destination filename already exists."""
    filename = "screenshot_2026-04-05_14-30-45_fullscreen.png"
    mocker.patch("pathlib.Path.is_file", return_value=False)
    fake_fd = 99
    fake_fp = MagicMock()
    fake_fp.__enter__ = MagicMock(return_value=fake_fp)
    fake_fp.__exit__ = MagicMock(return_value=False)
    # First os.open call (base filename) raises FileExistsError; second (_1) succeeds.
    mocker.patch("storage.os.open", side_effect=[FileExistsError(), fake_fd])
    mocker.patch("storage.os.fdopen", return_value=fake_fp)
    img = MagicMock(spec=Image.Image)

    result = storage.save_image(img, tmp_path, filename)

    expected = tmp_path / "screenshot_2026-04-05_14-30-45_fullscreen_1.png"
    assert result == expected
    img.save.assert_called_once_with(fake_fp, format="PNG")
