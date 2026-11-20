"""每日/周常总编排：跑 MFABD2 任务，全程盯钻石、卡剧情自动跳过。

任务前后各读一次顶栏货币（bd2_guard），钻石/付费钻石只要变少就立刻杀掉任务进程并报警。
跑任务时另起一个“剧情助推”线程：一旦画面出现剧情快进图标（F2）就按 F2 + 点屏幕中央，
这样周常里夹的剧情/结算不会把 MFABD2 卡死。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bd2 import win32, vision, imgio  # noqa: E402
import bd2_guard  # noqa: E402
import bd2_ledger  # noqa: E402
import story_ocr  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.environ.get("BD2_TOOLS") or os.path.join(os.path.dirname(HERE), "bd2-tools")
MF_PY = os.path.join(TOOLS, r"MFABD2\python\python.exe")
HEADLESS = os.path.join(TOOLS, "mfabd2_headless.py")
NO_WIN = 0x08000000
GAME = ("BrownDust II", "UnityWndClass")

# key -> (MFABD2 入口, 超时秒)
# 入口两种：interface.json 里的任务名（--task-entry），或 pipeline 里的节点名（--entry）
TASKS = {
    "rewards": ("RewardsDaily_Start", 600),
    "daily": ("Daily_HomePage", 1800),
    "weekly": ("Weekly_Start", 2400),
    "mail": ("Mail_HomePage", 600),
    "pass": ("Pass_HomePage", 600),
    "activity": ("Event_HomePage", 900),
    "freegacha": ("GachaADV_Start", 600),
    # 其余日常内容（都不花钻石，套利只花金币）
    "quick": ("QuickHunt_Start", 600),
    "collect": ("Collect_StartGame_HomePage", 1500),
    "arbitrage": ("Arbitrage_Start", 2700),
}
# 直接跑 pipeline 节点（不是任务入口），用于从日常里单独切出亲密度段
TASKS_RAW = {
    "guest": ("Daily_Intimacy_HUB", 900),
}
# 跑我们自己写的脚本（不进 MFABD2）
TASKS_SCRIPT = {
    "gueststory": ("bd2_guest_story.py", 2400),   # 有缘之客 · 来访剧情自动看完
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def ensure_window() -> int | None:
    hwnd = win32.find_window(*GAME)
    if not hwnd:
        return None
    try:
        x, y, w, h = win32.client_rect(hwnd)
        if (w, h) != (1920, 1080) or abs(x) > 8 or abs(y) > 40:
            win32.set_borderless(hwnd, 1920, 1080)
            log(f"窗口归位 {(x, y, w, h)} -> (0,0,1920,1080)")
    except Exception as exc:  # noqa: BLE001
        log(f"窗口归位失败: {exc}")
    return hwnd


class StoryBooster(threading.Thread):
    """子进程跑任务时，替它清掉剧情/结算卡点。"""

    daemon = True

    def __init__(self, hwnd: int) -> None:
        super().__init__()
        self.hwnd = hwnd
        self.stop_flag = threading.Event()
        self.tpl = imgio.read_bmp(os.path.join(HERE, r"templates\story_f2.bmp"))
        self.boosted = 0
        self._last = 0.0
        self._bad_rect = None

    def run(self) -> None:
        tick = 0
        try:
            while not self.stop_flag.is_set():
                time.sleep(1.6)
                tick += 1
                # 切屏/换显示器会把窗口甩到屏幕外，抓图只剩黑边；定期拉回 (0,0)
                # 注意：过场时游戏自己会短暂改窗口尺寸，必须连续两次异常才动手，否则会打断加载
                if tick % 4 == 0:
                    try:
                        x, y, w, h = win32.client_rect(self.hwnd)
                        bad = (w, h) != (1920, 1080) or abs(x) > 8 or abs(y) > 40
                        if bad and self._bad_rect == (x, y, w, h):
                            win32.set_borderless(self.hwnd, 1920, 1080)
                            log(f"窗口被挪走 {(x, y, w, h)}，已拉回全屏")
                            self._bad_rect = None
                        else:
                            self._bad_rect = (x, y, w, h) if bad else None
                    except Exception:
                        pass
                try:
                    with win32.Grabber(self.hwnd) as g:
                        frame = g.grab()
                except Exception:
                    continue
                # 沙盒（最后一夜）里 MFABD2 找不到"回大厅"按钮会原地打转，这里替它按右上九宫格
                if tick % 6 == 0:
                    try:
                        texts = [t for t, *_ in story_ocr._boxes(frame)]
                        if any(k in t for t in texts for k in ("进行快速探索", "移动魔法阵", "卢戈森林")):
                            log("检测到卡在最后一夜/移动魔法阵，点右上九宫格回大厅")
                            win32.focus(self.hwnd)
                            win32.click_client(self.hwnd, 1845, 85)
                            time.sleep(1.5)
                            continue
                    except Exception:
                        pass
                # 餐厅营业额/累计奖励这种弹窗会把整条流水线卡死；只点"一键获得/结算"，绝不碰购买
                if tick % 2 == 0:
                    try:
                        boxes = story_ocr._boxes(frame)
                        for t, x1, y1, x2, y2 in boxes:
                            if "一键获得" in t or t.strip() == "结算":
                                log(f"清餐厅弹窗（点 {t}）")
                                win32.focus(self.hwnd)
                                win32.click_client(self.hwnd, (x1 + x2) // 2, (y1 + y2) // 2)
                                time.sleep(1.2)
                                break
                        else:
                            if any("点击画面即可返回" in t for t, *_ in boxes):
                                win32.click_client(self.hwnd, 960, 700)
                                time.sleep(1.2)
                                continue
                            # 餐厅「营业额现状 / 渔笼收获」小窗会反复弹出挡住底栏
                            if any(k in t for t, *_ in boxes for k in ("渔笼收获情况", "餐馆营业额现状")):
                                for t, x1, y1, x2, y2 in boxes:
                                    if t.strip() == "取消":
                                        win32.focus(self.hwnd)
                                        win32.click_client(self.hwnd, (x1 + x2) // 2, (y1 + y2) // 2)
                                        time.sleep(1.1)
                                        break
                    except Exception:
                        pass
                s, _ = vision.find(frame, self.tpl, (1500, 10, 400, 120), 4)
                if s >= 0.92 and time.time() - self._last > 1.2:
                    win32.focus(self.hwnd)
                    send_vk(0x71)  # F2
                    win32.click_client(self.hwnd, 960, 620)
                    self._last = time.time()
                    self.boosted += 1
        except Exception as exc:  # noqa: BLE001
            log(f"剧情助推线程退出: {exc}")

    def stop(self) -> None:
        self.stop_flag.set()


def send_vk(vk: int) -> None:
    import ctypes
    u = ctypes.windll.user32
    u.keybd_event(vk, 0, 0, 0)
    time.sleep(0.04)
    u.keybd_event(vk, 0, 2, 0)


def run_task(entry: str, timeout: int, hwnd: int, raw: bool = False,
             tries: int = 0) -> tuple[int, float]:
    ts = time.strftime("%Y%m%d-%H%M%S")
    logfile = os.path.join(TOOLS, "logs", f"auto-{entry}-{ts}.log")
    os.makedirs(os.path.dirname(logfile), exist_ok=True)
    cmd = [
        MF_PY, "-u", HEADLESS,
        "--entry" if raw else "--task-entry", entry,
        "--task-timeout", str(timeout),
        "--resolution", "1080p",
        "--minimize", "no",
        "--log-file", logfile,
    ]
    t0 = time.time()
    out_path = logfile + ".out"
    fout = open(out_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        cmd, cwd=TOOLS, stdout=fout, stderr=subprocess.STDOUT,
        creationflags=NO_WIN,
    )
    booster = StoryBooster(hwnd)
    booster.start()
    while proc.poll() is None:
        time.sleep(1.0)
    booster.stop()
    fout.close()
    dur = time.time() - t0
    if proc.returncode not in (0, None):
        try:
            tail = open(out_path, encoding="utf-8", errors="replace").read()[-400:].strip()
            if tail:
                log(f"{entry} 子进程输出尾部: {tail}")
        except Exception:
            pass
        if dur < 5 and tries < 1:
            # 秒退通常是窗口没被 MFABD2 认出来，把游戏拉到前台再试一次（只重试一次）
            log(f"{entry} 秒退（rc={proc.returncode}），激活游戏窗口后重试")
            win32.focus(hwnd)
            time.sleep(1.0)
            return run_task(entry, timeout, hwnd, raw, tries + 1)
    log(f"{entry} 结束（{dur:.0f}s，剧情助推 {booster.boosted} 次）日志 {logfile}")
    return (proc.returncode or 0), dur


def clear_popup(hwnd: int) -> bool:
    """餐厅「营业额现状 / 累计奖励 / 渔笼收获」小窗会周期性盖住大厅底栏，
    遮住「抽抽乐/珍藏集」导致 at_lobby 误判。只点 一键获得/取消/点屏，绝不碰购买类按钮。"""
    try:
        with win32.Grabber(hwnd) as g:
            f = g.grab()
        boxes = story_ocr._boxes(f)
        texts = [t for t, *_ in boxes]
        if not any(k in t for t in texts for k in ("餐馆营业额现状", "累计奖励", "渔笼收获情况", "点击画面即可返回")):
            return False
        win32.focus(hwnd)
        for t, x1, y1, x2, y2 in boxes:
            if "一键获得" in t or t.strip() == "取消":
                win32.click_client(hwnd, (x1 + x2) // 2, (y1 + y2) // 2)
                time.sleep(1.1)
                return True
        win32.click_client(hwnd, 960, 700)
        time.sleep(1.1)
        return True
    except Exception:
        return False


def at_lobby(hwnd: int) -> bool:
    try:
        with win32.Grabber(hwnd) as g:
            f = g.grab()
        texts = [t for t, *_ in story_ocr._boxes(f)]
        # 大厅有两种呈现：底栏（抽抽乐/珍藏集）和右上快捷菜单（格鲁TALK/快速狩猎/心契之约）。
        # 注意「珍藏集增益」这种面板也会出现"珍藏集"字样，所以要凑够 2 个特征才算大厅。
        hits = sum(1 for k in ("抽抽乐", "快速狩猎", "快速特猎", "心契之约", "格鲁TALK", "格鲁 TALK",
                               "街机游戏", "战术教材", "通行证", "MASTER", "我的小屋", "好友")
                   if any(k in t for t in texts))
        if hits >= 2:
            return True
        if any(k in t for t in texts for k in ("餐馆营业额现状", "渔笼收获情况")):
            if clear_popup(hwnd):
                with win32.Grabber(hwnd) as g:
                    f2 = g.grab()
                t2 = [t for t, *_ in story_ocr._boxes(f2)]
                return sum(1 for k in ("抽抽乐", "快速狩猎", "心契之约", "格鲁TALK",
                                       "街机游戏", "战术教材", "通行证", "MASTER", "我的小屋", "好友")
                           if any(k in t for t in t2)) >= 2
        return False
    except Exception:
        return False


def go_lobby(hwnd: int, tries: int = 4) -> bool:
    """顶栏在不同界面会换位置，读数前必须先站到大厅，否则会把付费钻读成钻石。

    实测三条退路：左上返回 → 右上九宫格菜单（最后一夜/移动魔法阵只能靠这个回大厅） → ESC
    """
    for _ in range(tries):
        if at_lobby(hwnd):
            return True
        win32.focus(hwnd)
        win32.click_client(hwnd, 80, 62)      # 左上返回
        time.sleep(1.0)
        if at_lobby(hwnd):
            return True
        win32.click_client(hwnd, 1845, 85)     # 右上九宫格（沙盒/地图里才有）
        time.sleep(1.4)
        if at_lobby(hwnd):
            return True
        send_vk(0x1B)                         # ESC
        time.sleep(0.9)
    return at_lobby(hwnd)


def read_currency_stable(hwnd: int, tries: int = 4) -> dict | None:
    """顶栏被面板挡住时 OCR 会读成 None/0，先退几层再读；读不全就当跳过校验，
    绝不能把"没读到"当成"钻石花光了"。"""
    if not go_lobby(hwnd):
        log("  回不到大厅，货币读数不可信，跳过校验")
        return None
    for i in range(tries):
        win32.focus(hwnd)
        cur = bd2_guard.read_currency(hwnd)
        if cur.get("diamond") and cur.get("paid") and cur.get("gold"):
            return cur
        if i < tries - 1:
            win32.click_client(hwnd, 80, 62)
            time.sleep(1.0)
    log(f"  货币读数不完整 {cur}")
    return None


def run_script(script: str, timeout: int) -> int:
    """跑我们自己写的纯脚本（不需要 MFABD2），输出同样落日志。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    logfile = os.path.join(TOOLS, "logs", f"auto-{os.path.basename(script)}-{ts}.log")
    os.makedirs(os.path.dirname(logfile), exist_ok=True)
    with open(logfile, "w", encoding="utf-8", errors="replace") as fh:
        try:
            rc = subprocess.call([sys.executable, "-u", os.path.join(HERE, script)],
                                 cwd=HERE, timeout=timeout, stdout=fh,
                                 stderr=subprocess.STDOUT)
        except subprocess.TimeoutExpired:
            log(f"{script} 超时（{timeout}s）")
            return 4
    log(f"{script} 结束（rc={rc}）日志 {logfile}")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="rewards,daily,weekly,mail,pass",
                    help="逗号分隔：rewards,daily,weekly,mail,pass,activity,freegacha")
    ap.add_argument("--max-hours", type=float, default=3.0)
    args = ap.parse_args()

    hwnd = ensure_window()
    if not hwnd:
        log("游戏未运行，先启动一次再跑（或直接双击 BD2助手 里的任务，它会自己拉起游戏）")
        return 2
    win32.focus(hwnd)
    time.sleep(0.8)

    before = read_currency_stable(hwnd)
    log(f"起始货币 {before}")
    if not before:
        log("警告：钻石数字没读到（可能不在大厅），全程只做记录不做强校验")
        before = {}

    start = time.time()
    for key in [k.strip() for k in args.tasks.split(",") if k.strip()]:
        raw = False
        script = None
        if key in TASKS:
            entry, timeout = TASKS[key]
        elif key in TASKS_RAW:
            entry, timeout = TASKS_RAW[key]
            raw = True
        elif key in TASKS_SCRIPT:
            script, timeout = TASKS_SCRIPT[key]
            entry = key
        else:
            log(f"跳过未知任务 {key}")
            continue
        if time.time() - start > args.max_hours * 3600:
            log("超过 --max-hours，停止")
            break
        hwnd = ensure_window() or hwnd
        log(f"开始 {key}（{entry}）")
        win32.focus(hwnd)
        t0 = time.time()
        if script:
            rc = run_script(script, timeout)
        else:
            rc, _ = run_task(entry, timeout, hwnd, raw)
        dur = time.time() - t0
        hwnd = ensure_window() or hwnd
        after = read_currency_stable(hwnd)
        if not after:
            log("货币没读到（还停在非大厅界面），本次跳过校验")
            bd2_ledger.append(key, before, None, dur, rc == 0, "货币没读到，未记账差值")
            continue
        if not before:
            log(f"取到基线货币 {after}（之前没读到，本次不做对比）")
            before = after
            bd2_ledger.append(key, None, after, dur, rc == 0, "基线缺失，只记结果")
            continue
        ok, msg = bd2_guard.check(before, after)
        log(f"货币校验: {msg}")
        bd2_ledger.append(key, before, after, dur, (rc == 0) and ok, msg)
        if not ok:
            log("!!! 钻石减少，立即停止全部任务 !!!")
            p = bd2_ledger.build_report()
            if p:
                log(f"收益日报已生成 {p}")
            return 3
        # 金币偶尔被 OCR 多读/少读一位，别让它污染下一次对比
        b, a = before.get("gold"), after.get("gold")
        if b and a and (a > b * 3 or a < b / 3):
            log(f"金币识别疑似抖动（{b}->{a}），沿用旧值")
            after["gold"] = b
        before = after

    log("全部完成")
    # 跑完立刻出一份「今天收益 / 花费」日报，并把任务页完成度一起写进去
    p = bd2_ledger.build_report()
    if p:
        items = bd2_ledger.read_task_page()
        if items:
            with open(p, "a", encoding="utf-8") as f:
                f.write("## 游戏任务页完成度\n\n")
                for it in items:
                    f.write(f"- {it}\n")
                f.write("\n")
        log(f"收益日报 {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
