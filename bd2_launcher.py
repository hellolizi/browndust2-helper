"""棕色尘埃2 一键助手（GUI）。

选任务 → 点「开始」→ 自动拉起游戏并执行。
所有任务都走本机脚本，不联网、不驻留后台。
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.environ.get("BD2_TOOLS") or os.path.join(os.path.dirname(HERE), "bd2-tools")
MF_PY = os.path.join(TOOLS, "MFABD2", "python", "python.exe")
HEADLESS = os.path.join(TOOLS, "mfabd2_headless.py")
OPTS_EQUIP = os.path.join(TOOLS, "opts_equip_force.json")
GAME_TITLE = "BrownDust II"
PROTOCOL = "browndust2:games/10000002?usn=0"

# 用 pythonw 打开界面时 sys.executable 也是 pythonw，转成 python.exe 才能接输出
PYEXE = sys.executable
if os.path.basename(PYEXE).lower() == "pythonw.exe":
    PYEXE = os.path.join(os.path.dirname(PYEXE), "python.exe")

NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

HEADLESS_BASE = [
    "--resolution", "1080p",
    "--screencap", "Background",
    "--account", "0",
    "--minimize", "no",
]

TASKS = [
    ("story", "自动剧情（主线，自动开游戏进剧情）"),
    ("rewards", "任务页 · 每日/每周奖励领取（纯领取，不花钻）"),
    ("daily", "日常任务（全量日常，不花钻）"),
    ("weekly", "周常任务（能做的都做，不花钻）"),
    ("mail", "领取邮件（不花钻）"),
    ("pass", "通行证奖励（不花钻）"),
    ("guest", "亲密度 · 每日谈心 3 次（不花钻）"),
    ("gueststory", "有缘之客 · 来访剧情全看（不花钻、不耗次数）"),
    ("quick", "日常 · 快速（14 项）"),
    ("full", "日常 · 全量（含采集/套利/装备）"),
    ("activity", "活动（Event 全跑）"),
    ("collect", "地图采集[完整]（约 10 分钟）"),
    ("arbitrage", "商店套利（约 25 分钟）"),
    ("equip", "装备制作&炼制（强制重跑）"),
]


def game_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {GAME_TITLE}.exe", "/NH"],
            capture_output=True, text=True, timeout=15, creationflags=NO_WIN,
        ).stdout
        return GAME_TITLE.lower() in out.lower()
    except Exception:
        return False


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue[str] = queue.Queue()
        self.stop_flag = False
        self.task_vars: dict[str, tk.BooleanVar] = {
            key: tk.BooleanVar(value=(key == "story")) for key, _ in TASKS
        }
        self.digest_var = tk.BooleanVar(value=True)
        cfg = {}
        try:
            with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
        api = cfg.get("api") or {}
        self.base_var = tk.StringVar(value=api.get("base_url", "https://api.deepseek.com/v1"))
        self.model_var = tk.StringVar(value=api.get("model", "deepseek-chat"))
        self.key_var = tk.StringVar(value=api.get("key", ""))

        root.title("棕色尘埃2 · 一键助手")
        root.geometry("760x520")
        root.minsize(680, 460)

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="勾选要跑的内容（可多选，按顺序依次执行）：", font=("Microsoft YaHei", 10, "bold")).pack(anchor="w")

        body = ttk.Frame(root, padding=(10, 0))
        body.pack(fill="x")
        for key, label in TASKS:
            ttk.Checkbutton(body, text=label, variable=self.task_vars[key]).pack(anchor="w", pady=1)

        mid = ttk.Frame(root, padding=(10, 8))
        mid.pack(fill="x")
        ttk.Checkbutton(mid, text="边跑边读对白并生成剧情梗概（需下面的 Key）", variable=self.digest_var).pack(anchor="w")
        self.report_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(mid, text="跑完自动生成「今日收益 / 花费」日报（不花钻、只读）",
                        variable=self.report_var).pack(anchor="w")
        ttk.Button(mid, text="今日日报", command=self.open_report).pack(side="right", padx=4)
        ttk.Button(mid, text="打开日志目录", command=self.open_logs).pack(side="right", padx=4)

        api_box = ttk.LabelFrame(root, text="梗概 API（OpenAI 兼容，留空则只存台词）", padding=8)
        api_box.pack(fill="x", padx=10)
        row1 = ttk.Frame(api_box)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="Key").pack(side="left")
        ttk.Entry(row1, textvariable=self.key_var, show="*", width=46).pack(side="left", padx=6)
        row2 = ttk.Frame(api_box)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="接口").pack(side="left")
        ttk.Entry(row2, textvariable=self.base_var, width=34).pack(side="left", padx=6)
        ttk.Label(row2, text="模型").pack(side="left")
        ttk.Entry(row2, textvariable=self.model_var, width=18).pack(side="left", padx=6)

        bar = ttk.Frame(root, padding=(10, 0))
        bar.pack(fill="x", pady=6)
        self.btn_start = ttk.Button(bar, text="开始", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(bar, text="停止", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=8)
        self.status = ttk.Label(bar, text="就绪")
        self.status.pack(side="left", padx=12)

        self.log = ScrolledText(root, height=18, font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log.configure(state="disabled")

        self.root.after(100, self.drain)

    # ---------- UI helpers ----------
    def write(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def drain(self) -> None:
        try:
            while True:
                self.write(self.q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def open_logs(self) -> None:
        d = os.path.join(TOOLS, "logs")
        os.startfile(d) if os.path.isdir(d) else messagebox.showinfo("提示", "还没有日志")

    def open_report(self) -> None:
        p = os.path.join(HERE, "收益日报-" + time.strftime("%Y%m%d") + ".md")
        if os.path.exists(p):
            os.startfile(p)
        else:
            messagebox.showinfo("提示", "今天还没有日报，先跑一次任务（勾选下面的日报选项）")

    # ---------- run ----------
    def build_cmd(self, key: str) -> list[str]:
        if key == "story":
            cmd = [PYEXE, "-u", os.path.join(HERE, "bd2_story.py")]
            if self.digest_var.get():
                k = self.key_var.get().strip()
                if k:
                    cmd += ["--api-key", k]
            else:
                cmd += ["--no-digest"]
            return cmd
        ts = time.strftime("%Y%m%d-%H%M%S")
        log = os.path.join(TOOLS, "logs", f"gui-{ts}.log")
        os.makedirs(os.path.join(TOOLS, "logs"), exist_ok=True)
        if key in ("rewards", "daily", "weekly", "mail", "pass", "guest", "gueststory",
                   "quick", "collect", "arbitrage"):
            # 这些走统一编排：窗口归位 + 钻石护栏 + 剧情助推
            return [PYEXE, "-u", os.path.join(HERE, "bd2_auto_daily.py"),
                    "--tasks", key, "--max-hours", "3"]
        cmd = [MF_PY, "-u", HEADLESS] + HEADLESS_BASE + ["--log-file", log]
        if key == "quick":
            cmd += ["--preset-key", "quick"]
        elif key == "full":
            cmd += ["--preset-key", "full"]
        elif key == "activity":
            cmd += ["--task-entry", "Event_HomePage", "--task-timeout", "900"]
        elif key == "collect":
            cmd += ["--task-entry", "Collect_StartGame_HomePage", "--task-timeout", "1200"]
        elif key == "arbitrage":
            cmd += ["--task-entry", "Arbitrage_Start", "--task-timeout", "2400"]
        elif key == "equip":
            cmd += ["--task-entry", "Equip_HomePage", "--options-json", OPTS_EQUIP, "--task-timeout", "900"]
        return cmd

    def ensure_game(self) -> bool:
        if game_running():
            self.q.put("[启动] 游戏已在运行")
            return True
        self.q.put("[启动] 游戏未运行，按官方协议拉起启动器…")
        os.startfile(PROTOCOL)
        for i in range(60):
            time.sleep(3)
            if game_running():
                self.q.put("[启动] 游戏已启动，等待 15 秒进标题…")
                time.sleep(15)
                return True
            if i % 10 == 9:
                self.q.put(f"[启动] 等待游戏窗口… {(i + 1) * 3}s")
        return False

    def save_api(self) -> None:
        try:
            p = os.path.join(HERE, "config.json")
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
            cfg["api"] = {
                "base_url": self.base_var.get().strip(),
                "key": self.key_var.get().strip(),
                "model": self.model_var.get().strip(),
            }
            with open(p, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            self.q.put(f"[配置] 保存失败 {exc}")

    def selected_keys(self) -> list[str]:
        order = [k for k, _ in TASKS]
        return [k for k in order if self.task_vars[k].get()]

    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo("提示", "已经在跑了，先停止再开")
            return
        keys = self.selected_keys()
        if not keys:
            messagebox.showinfo("提示", "至少勾选一项")
            return
        self.stop_flag = False
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.status.configure(text="启动中…")
        self.save_api()
        threading.Thread(target=self._run, args=(keys,), daemon=True).start()

    def _run(self, keys: list[str]) -> None:
        try:
            if not self.ensure_game():
                self.q.put("[启动] 游戏启动超时，已中止")
                return
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
            for idx, key in enumerate(keys, 1):
                if self.stop_flag:
                    self.q.put("[队列] 已被停止，剩余任务不执行")
                    break
                label = dict(TASKS).get(key, key)
                self.q.put(f"[队列 {idx}/{len(keys)}] {label}")
                cmd = self.build_cmd(key)
                self.q.put("[执行] " + " ".join(cmd))
                cwd = HERE if cmd[0] == PYEXE else TOOLS
                self.proc = subprocess.Popen(
                    cmd, cwd=cwd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", env=env,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | NO_WIN,
                )
                assert self.proc.stdout is not None
                for line in self.proc.stdout:
                    self.q.put(line.rstrip())
                code = self.proc.wait()
                self.q.put(f"[结束] {label} 退出码 {code}")
                if code != 0 and self.stop_flag:
                    break
        except Exception as exc:  # noqa: BLE001
            self.q.put(f"[错误] {exc}")
        finally:
            if self.report_var.get():
                self._make_report()
            self.root.after(0, self._done)

    def _make_report(self) -> None:
        """整队跑完后汇总今天的收益与花费，正文直接打到界面里，同时落 md 文件。"""
        try:
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            r = subprocess.run([PYEXE, "-u", os.path.join(HERE, "bd2_ledger.py"), "--report", "--task-page"],
                               cwd=HERE, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=env, creationflags=NO_WIN, timeout=180)
            p = (r.stdout or "").strip().splitlines()
            path = p[-1].strip() if p else ""
            if not path or not os.path.exists(path):
                self.q.put("[日报] 今天还没有账本记录")
                return
            self.q.put("[日报] " + path)
            with open(path, encoding="utf-8") as f:
                for line in f.read().splitlines():
                    self.q.put(line)
        except Exception as exc:  # noqa: BLE001
            self.q.put(f"[日报] 生成失败 {exc}")

    def _done(self) -> None:
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.status.configure(text="就绪")

    def stop(self) -> None:
        self.stop_flag = True
        if self.proc and self.proc.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                    capture_output=True, timeout=20, creationflags=NO_WIN,
                )
                self.q.put("[停止] 已结束任务进程")
            except Exception as exc:  # noqa: BLE001
                self.q.put(f"[停止] 失败 {exc}")
        self.status.configure(text="已停止")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
