# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Captura — macOS .app bundle
# Requires PyInstaller >= 6.6.0
#
# Build:
#   pip install "pyinstaller>=6.6.0"
#   pyinstaller captura.spec --noconfirm
#
# Output: dist/Captura.app

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        # App assets
        ("imgs", "imgs"),
        # customtkinter ships themes, fonts, and images as package data;
        # they must be bundled explicitly or the app launches with no styling.
        *collect_data_files("customtkinter"),
    ],
    hiddenimports=[
        # customtkinter loads widget modules dynamically at runtime.
        *collect_submodules("customtkinter"),
        # Pillow's Tkinter bridge is not always detected by the static analyser.
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Test and dev tooling — not needed in the bundle.
        "pytest",
        "pytest_mock",
        "pytest_cov",
        "ruff",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Captura",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # No terminal window — pure GUI app.
    argv_emulation=False,   # Must be False for CustomTkinter on macOS.
    target_arch=None,       # None = native arch; set "universal2" for fat binary.
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Captura",
)

app = BUNDLE(
    coll,
    name="Captura.app",
    icon=None,              # Replace with "imgs/icon.icns" once an icon is added.
    bundle_identifier="com.captura.app",
    info_plist={
        "CFBundleName": "Captura",
        "CFBundleDisplayName": "Captura",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": True,
        # Required by macOS for any app that captures screen content.
        "NSScreenCaptureUsageDescription": (
            "Captura needs Screen Recording permission to capture screenshots."
        ),
    },
)
