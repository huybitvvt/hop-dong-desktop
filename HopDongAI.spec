# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project = Path(SPECPATH)
a = Analysis(
    [str(project / 'main.py')],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(project / 'assets'), 'assets')],
    hiddenimports=['keyring.backends.Windows', 'keyring.backends.fail', 'win32ctypes.pywin32.win32cred'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'tkinter', 'PySide6.QtTest', 'rapidocr', 'onnxruntime', 'tesserocr', 'cv2', 'numpy', 'pypdfium2', 'fitz', 'pymupdf', 'torch', 'paddle'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='HopDongAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(project / 'assets' / 'app.ico'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='HopDongAI')
