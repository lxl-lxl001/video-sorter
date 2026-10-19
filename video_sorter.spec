# -*- mode: python ; coding: utf-8 -*-
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

# 注意这里去掉了 a.binaries 和 a.datas，并加上 exclude_binaries=True
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoSorter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # 隐藏黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# 收集所有文件到同一个文件夹中
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VideoSorter",      # 最终生成的文件夹名就叫 VideoSorter
)
