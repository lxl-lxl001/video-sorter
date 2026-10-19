# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — onefile + windowed + 显式收集 imageio_ffmpeg 自带的 ffmpeg 二进制。
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 收集 imageio_ffmpeg 里的所有非 .py 文件（包含 binaries/ffmpeg-*.exe）
datas = collect_data_files("imageio_ffmpeg")
# 保证子模块都被打进去
hiddenimports = collect_submodules("imageio_ffmpeg")

a = Analysis(
    ["video_sorter.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VideoSorter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # --windowed
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
