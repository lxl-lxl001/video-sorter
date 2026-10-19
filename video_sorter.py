#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频按时长自动分类工具
- 第一遍：按 <60s / 60s~1h / >=1h 分类到一级文件夹
- 第二遍：仅当一级文件夹【根下】视频文件数 > 12 时，才按 10 秒 / 10 分 / 10 时细分
"""
import os
import re
import sys
import queue
import shutil
import subprocess
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import imageio_ffmpeg


# ============ 常量 ============
VIDEO_EXTS = {
    '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v',
    '.ts', '.mpg', '.mpeg', '.m2ts', '.3gp', '.asf', '.vob', '.ogv',
    '.rm', '.rmvb', '.f4v', '.divx',
}

DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+)(?:\.(\d+))?")

FIRST_BUCKETS = ["0-60秒", "1-60分", "1-60时"]

SECOND_LEVEL = {
    "0-60秒": [
        ("0-10秒",   0.0,    10.0),
        ("10-20秒",  10.0,   20.0),
        ("20-30秒",  20.0,   30.0),
        ("30-40秒",  30.0,   40.0),
        ("40-50秒",  40.0,   50.0),
        ("50-60秒",  50.0,   60.0),
    ],
    "1-60分": [
        ("0-10分",   0.0,     600.0),
        ("10-20分",  600.0,   1200.0),
        ("20-30分",  1200.0,  1800.0),
        ("30-40分",  1800.0,  2400.0),
        ("40-50分",  2400.0,  3000.0),
        ("50-60分",  3000.0,  3600.0),
    ],
    "1-60时": [
        ("0-10时",   0.0,      36000.0),
        ("10-20时",  36000.0,  72000.0),
        ("20-30时",  72000.0,  108000.0),
        ("30-40时",  108000.0, 144000.0),
        ("40-50时",  144000.0, 180000.0),
        ("50-60时",  180000.0, 216000.0),
        ("60时以上", 216000.0, float("inf")),
    ],
}

_CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ============ 工具函数 ============
def is_video_file(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def get_duration_seconds(path, timeout=30):
    """调用 imageio-ffmpeg 自带的 ffmpeg 读取时长（秒），超时/失败抛异常。"""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", path],
        capture_output=True,
        timeout=timeout,
        creationflags=_CREATIONFLAGS,
    )
    stderr = proc.stderr.decode("utf-8", errors="ignore")
    m = DURATION_RE.search(stderr)
    if not m:
        raise ValueError("无法从 ffmpeg 输出中解析出时长")
    h, mi, s, frac = m.groups()
    total = int(h) * 3600 + int(mi) * 60 + int(s)
    if frac:
        total += float("0." + frac)
    return total


def unique_dest(dest_path):
    """目标已存在则自动重命名为 名称(1).ext、名称(2).ext ..."""
    if not os.path.exists(dest_path):
        return dest_path
    base, ext = os.path.splitext(dest_path)
    i = 1
    while True:
        cand = f"{base}({i}){ext}"
        if not os.path.exists(cand):
            return cand
        i += 1


def classify_first(duration):
    if duration < 60:
        return "0-60秒"
    elif duration < 3600:
        return "1-60分"
    else:
        return "1-60时"


def classify_second(duration, buckets):
    for name, lo, hi in buckets:
        if lo <= duration < hi:
            return name
    return None


def format_duration(seconds):
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h}时{m}分{s}秒"
    if m > 0:
        return f"{m}分{s}秒"
    return f"{s}秒"


# ============ 后台工作线程 ============
def run_job(src_dir, dst_dir, mode, q):
    try:
        ok = skipped = failed = 0

        # ===== 阶段 1：扫描 =====
        q.put(("status", "scanning"))
        q.put(("log", "开始扫描源文件夹..."))
        files = []

        def on_walk_error(e):
            q.put(("log", f"⚠ 扫描警告：{e}"))

        for root_dir, _dirs, fnames in os.walk(src_dir, onerror=on_walk_error):
            for fn in fnames:
                fp = os.path.join(root_dir, fn)
                try:
                    if is_video_file(fn) and os.path.isfile(fp):
                        files.append(fp)
                except OSError:
                    continue

        total = len(files)
        q.put(("log", f"共发现 {total} 个视频文件"))
        q.put(("total", total))

        if total == 0:
            q.put(("done", 0, 0, 0))
            return

        # ===== 阶段 2：第一遍分类 =====
        q.put(("status", "processing"))
        for i, fp in enumerate(files, 1):
            fname = os.path.basename(fp)
            try:
                dur = get_duration_seconds(fp)
            except subprocess.TimeoutExpired:
                skipped += 1
                q.put(("log", f"⏱ 超时跳过：{fname}"))
                q.put(("progress", i, total))
                continue
            except Exception as e:
                skipped += 1
                q.put(("log", f"⚠ 读取时长失败跳过：{fname}（{e}）"))
                q.put(("progress", i, total))
                continue

            bucket = classify_first(dur)
            dest_dir = os.path.join(dst_dir, bucket)
            try:
                os.makedirs(dest_dir, exist_ok=True)
            except OSError as e:
                failed += 1
                q.put(("log", f"❌ 创建目录失败：{dest_dir}（{e}）"))
                q.put(("progress", i, total))
                continue

            dest = unique_dest(os.path.join(dest_dir, fname))
            try:
                if mode == "copy":
                    shutil.copy2(fp, dest)
                else:
                    shutil.move(fp, dest)
                ok += 1
                q.put(("log", f"正在处理 {fname} (时长 {format_duration(dur)}) → {bucket}"))
            except Exception as e:
                failed += 1
                q.put(("log", f"❌ 处理失败：{fname}（{e}）"))
            q.put(("progress", i, total))

        # ===== 阶段 3：统一统计三个一级文件夹根下的视频数 =====
        q.put(("log", "第一次分类完成，开始检查是否需要二次细分..."))
        counts = {}
        for bucket in FIRST_BUCKETS:
            bucket_dir = os.path.join(dst_dir, bucket)
            counts[bucket] = 0
            if not os.path.isdir(bucket_dir):
                continue
            try:
                with os.scandir(bucket_dir) as it:
                    for entry in it:
                        try:
                            if entry.is_file() and is_video_file(entry.name):
                                counts[bucket] += 1
                        except OSError:
                            continue
            except OSError as e:
                q.put(("log", f"⚠ 无法统计 {bucket}：{e}"))

        # ===== 阶段 4：对达标的文件夹执行二次细分（各自独立） =====
        for bucket in FIRST_BUCKETS:
            if counts[bucket] <= 12:
                q.put(("log", f"{bucket} 根下视频 {counts[bucket]} 个（≤12），不细分"))
                continue

            q.put(("log", f"{bucket} 根下视频 {counts[bucket]} 个（>12），执行二次细分"))
            bucket_dir = os.path.join(dst_dir, bucket)
            sub_buckets = SECOND_LEVEL[bucket]
            sub_dirs = {}
            for name, _lo, _hi in sub_buckets:
                sd = os.path.join(bucket_dir, name)
                try:
                    os.makedirs(sd, exist_ok=True)
                    sub_dirs[name] = sd
                except OSError as e:
                    q.put(("log", f"⚠ 无法创建二级目录 {bucket}/{name}：{e}"))

            root_videos = []
            try:
                with os.scandir(bucket_dir) as it:
                    for entry in it:
                        try:
                            if entry.is_file() and is_video_file(entry.name):
                                root_videos.append(entry.path)
                        except OSError:
                            continue
            except OSError as e:
                q.put(("log", f"⚠ 无法读取 {bucket}：{e}"))
                continue

            for fp in root_videos:
                fname = os.path.basename(fp)
                try:
                    dur = get_duration_seconds(fp)
                except Exception as e:
                    q.put(("log", f"⚠ 二次细分读取时长失败，保持原位：{fname}（{e}）"))
                    continue
                sub_name = classify_second(dur, sub_buckets)
                if sub_name is None or sub_name not in sub_dirs:
                    q.put(("log", f"⚠ 无法归类，保持原位：{fname}"))
                    continue
                dest = unique_dest(os.path.join(sub_dirs[sub_name], fname))
                try:
                    shutil.move(fp, dest)
                    q.put(("log", f"二次细分：{fname} (时长 {format_duration(dur)}) → {bucket}/{sub_name}"))
                except Exception as e:
                    q.put(("log", f"❌ 二次细分移动失败：{fname}（{e}）"))

        q.put(("done", ok, skipped, failed))

    except Exception:
        q.put(("fatal", traceback.format_exc()))


# ============ 界面 ============
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("视频按时长自动分类工具")
        self.root.geometry("820x620")
        self.root.minsize(640, 480)

        self.src_var = tk.StringVar()
        self.dst_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="copy")
        self.status_var = tk.StringVar(value="就绪")

        self.total = 0
        self.running = False
        self.q = queue.Queue()

        self._build_ui()
        self.root.after(80, self._poll_queue)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        row1 = ttk.Frame(outer); row1.pack(fill="x", pady=(0, 6))
        ttk.Button(row1, text="选择源文件夹", width=14, command=self._choose_src).pack(side="left")
        ttk.Entry(row1, textvariable=self.src_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(8, 0))

        row2 = ttk.Frame(outer); row2.pack(fill="x", pady=(0, 6))
        ttk.Button(row2, text="选择目标文件夹", width=14, command=self._choose_dst).pack(side="left")
        ttk.Entry(row2, textvariable=self.dst_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(8, 0))

        row3 = ttk.Frame(outer); row3.pack(fill="x", pady=(0, 6))
        ttk.Label(row3, text="操作方式：").pack(side="left")
        ttk.Radiobutton(row3, text="复制", value="copy", variable=self.mode_var).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(row3, text="移动", value="move", variable=self.mode_var).pack(side="left")

        row4 = ttk.Frame(outer); row4.pack(fill="x", pady=(0, 6))
        self.start_btn = ttk.Button(row4, text="开始", width=14, command=self._on_start)
        self.start_btn.pack(side="left")
        ttk.Label(row4, textvariable=self.status_var).pack(side="left", padx=(12, 0))

        row5 = ttk.Frame(outer); row5.pack(fill="x", pady=(0, 6))
        self.progress = ttk.Progressbar(row5, mode="determinate", maximum=100)
        self.progress.pack(fill="x", expand=True)

        log_frame = ttk.LabelFrame(outer, text="日志")
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=16, wrap="word", state="disabled")
        vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=vsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def _choose_src(self):
        p = filedialog.askdirectory(title="选择源文件夹")
        if p:
            self.src_var.set(os.path.normpath(p))

    def _choose_dst(self):
        p = filedialog.askdirectory(title="选择目标文件夹")
        if p:
            self.dst_var.set(os.path.normpath(p))

    def _append_log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _validate(self):
        src = self.src_var.get().strip()
        dst = self.dst_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showwarning("提示", "请选择有效的源文件夹")
            return False
        if not dst or not os.path.isdir(dst):
            messagebox.showwarning("提示", "请选择有效的目标文件夹")
            return False
        s = os.path.normcase(os.path.abspath(src))
        d = os.path.normcase(os.path.abspath(dst))
        if s == d:
            messagebox.showerror("错误", "源文件夹与目标文件夹不能相同")
            return False
        if d.startswith(s + os.sep) or s.startswith(d + os.sep):
            messagebox.showerror("错误", "源文件夹与目标文件夹不能互为子目录")
            return False
        return True

    def _on_start(self):
        if self.running:
            return
        if not self._validate():
            return

        src = os.path.abspath(self.src_var.get().strip())
        dst = os.path.abspath(self.dst_var.get().strip())
        mode = self.mode_var.get()

        self.running = True
        self.start_btn.configure(state="disabled")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=100, value=0)
        self.status_var.set("准备中...")
        self.total = 0

        threading.Thread(target=run_job, args=(src, dst, mode, self.q), daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "log":
            self._append_log(msg[1])
        elif kind == "status":
            if msg[1] == "scanning":
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
                self.status_var.set("扫描中...")
            elif msg[1] == "processing":
                self.progress.stop()
                self.progress.configure(mode="determinate", maximum=100, value=0)
                self.status_var.set("处理中...")
        elif kind == "total":
            self.total = msg[1]
        elif kind == "progress":
            i, total = msg[1], msg[2]
            if total > 0:
                pct = i * 100.0 / total
                self.progress.configure(mode="determinate", maximum=100)
                self.progress["value"] = pct
                self.status_var.set(f"已处理 {i}/{total}（{pct:.0f}%）")
        elif kind == "done":
            ok, skipped, failed = msg[1], msg[2], msg[3]
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=100, value=100)
            self.status_var.set(f"完成：成功 {ok}，跳过 {skipped}，失败 {failed}")
            self._append_log("✅ 分类已完成")
            self.start_btn.configure(state="normal")
            self.running = False
            messagebox.showinfo("完成", f"已完成：成功 {ok} 个，跳过 {skipped} 个，失败 {failed} 个")
        elif kind == "fatal":
            self.progress.stop()
            self._append_log("❌ 发生严重错误：\n" + msg[1])
            self.start_btn.configure(state="normal")
            self.running = False
            messagebox.showerror("错误", "处理过程中发生错误，请查看日志")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
