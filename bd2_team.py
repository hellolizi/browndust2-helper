"""自动编队 / 战败换阵容重试 / 角色升级（半自动：首次需一次性标定坐标）。

设计取舍：
- 编队界面在不同模式（剧情战斗、活动战斗、狩猎）布局不同，硬编码坐标必错，
  所以把「按钮位置 / 槽位位置 / 角色列表网格」全部放到 team_config.json，
  由 calibrate 子命令用鼠标实时取点生成，脚本只负责按配置点。
- 战败检测用一张模板（templates/defeat.bmp）+ ROI，判定为模板匹配，
  命中后按 teams 列表轮换下一套阵容重建队伍并重开战斗，带次数上限防死循环。
- 升级走「指定次数」而不是「升到满级」：升级消耗金币/材料，必须有上限。

用法：
    python bd2_team.py calibrate            # 交互标定，生成 team_config.json
    python bd2_team.py build --variant 0    # 按第 0 套阵容配队并开战
    python bd2_team.py retry --max 4        # 战败自动换阵容重试，最多 4 次
    python bd2_team.py levelup --times 3    # 给当前角色点 3 次升级
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

from bd2 import imgio, vision, win32

CFG_PATH = "team_config.json"


def load_cfg() -> dict:
    if not os.path.exists(CFG_PATH):
        sys.exit(f"缺少 {CFG_PATH}，先运行：python bd2_team.py calibrate")
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def hwnd_or_exit(title: str, cls: str) -> int:
    hwnd = win32.find_window(title, cls)
    if not hwnd:
        sys.exit("没有找到游戏窗口")
    if not win32.focus(hwnd):
        sys.exit("无法激活游戏窗口")
    return hwnd


def tap(hwnd: int, xy, delay: float = 0.7) -> None:
    win32.click_client(hwnd, int(xy[0]), int(xy[1]))
    time.sleep(delay)


def grid_point(roster: dict, idx: int) -> list[int]:
    cols = int(roster["cols"])
    r, c = divmod(int(idx), cols)
    ox, oy = roster["origin"]
    return [ox + c * int(roster["dx"]), oy + r * int(roster["dy"])]


# ---------------- 标定 ----------------

CALIB_STEPS = [
    ("edit_team", "战斗准备界面的【编辑队伍】按钮（或队伍图标）"),
    ("confirm", "选人弹窗里的【确定/使用】按钮"),
    ("start_battle", "战斗准备界面的【开始战斗】按钮"),
    ("slot_first", "第 1 个编队槽位中心"),
    ("roster_first", "角色列表里第 1 个可点角色的头像中心"),
]


def cmd_calibrate(args) -> None:
    hwnd = hwnd_or_exit(args.title, args.cls)
    x0, y0, _, _ = win32.client_rect(hwnd)
    cfg = {
        "window": {"title": args.title, "class": args.cls},
        "delay_edit": 2.5,
        "clear_slots": False,
        "teams": [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9]],
        "levels": {"open": [0, 0], "button": [0, 0], "times": 3},
    }
    pts: dict[str, list[int]] = {}
    print("把鼠标停在目标位置，然后按回车记录；输入 s 跳过。\n")
    for key, desc in CALIB_STEPS:
        while True:
            ans = input(f"[{key}] {desc} -> 回车记录 / s 跳过: ").strip().lower()
            if ans == "s":
                break
            sx, sy = win32.cursor_pos()
            pts[key] = [sx - x0, sy - y0]
            print(f"    记录 {pts[key]}")
            break

    if "slot_first" in pts:
        step = args.slot_step
        cfg["slots"] = [[pts["slot_first"][0] + i * step, pts["slot_first"][1]] for i in range(5)]
        print(f"    槽位按 step={step} 生成: {cfg['slots']}")
    if "roster_first" in pts:
        cfg["roster"] = {
            "origin": pts["roster_first"],
            "cols": args.roster_cols,
            "dx": args.roster_dx,
            "dy": args.roster_dy,
        }
    for key in ("edit_team", "confirm", "start_battle"):
        if key in pts:
            cfg[key] = pts[key]
    if "edit_team" in pts:
        cfg["levels"]["open"] = pts["edit_team"]

    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"\n已写入 {CFG_PATH}。请按需手工调整 teams / slots / roster 网格参数。")


# ---------------- 编队 ----------------

def build_team(hwnd: int, cfg: dict, variant: int) -> None:
    teams = cfg.get("teams") or []
    if not teams:
        sys.exit("team_config.json 里没有 teams")
    picks = teams[variant % len(teams)]
    print(f"使用阵容 #{variant % len(teams)}: {picks}")

    if cfg.get("edit_team"):
        tap(hwnd, cfg["edit_team"], cfg.get("delay_edit", 2.5))

    slots = cfg.get("slots") or []
    roster = cfg.get("roster") or {}
    for i, slot in enumerate(slots):
        if i >= len(picks):
            break
        tap(hwnd, slot, 1.0)
        tap(hwnd, grid_point(roster, picks[i]), 1.0)
        if cfg.get("confirm"):
            tap(hwnd, cfg["confirm"], 1.2)

    if cfg.get("start_battle"):
        tap(hwnd, cfg["start_battle"], 1.5)


def cmd_build(args) -> None:
    cfg = load_cfg()
    hwnd = hwnd_or_exit(cfg["window"]["title"], cfg["window"]["class"])
    build_team(hwnd, cfg, args.variant)


# ---------------- 战败重试 ----------------

def wait_defeat(hwnd: int, cfg: dict, timeout: float) -> bool:
    rect = tuple(cfg.get("defeat_roi", [0, 0, 1920, 1080]))
    tpl = imgio.read_bmp(os.path.join("templates", "defeat.bmp"))
    thr = float(cfg.get("defeat_thr", 0.85))
    end = time.time() + timeout
    with win32.Grabber(hwnd) as g:
        while time.time() < end:
            try:
                frame = g.grab()
            except Exception as e:
                print(f"截图失败: {e}")
                time.sleep(0.5)
                continue
            s, loc = vision.find(frame, tpl, rect, 4)
            if s >= thr:
                print(f"检测到战败 ({s:.2f})")
                return True
            time.sleep(0.8)
    return False


def cmd_retry(args) -> None:
    cfg = load_cfg()
    if not os.path.exists(os.path.join("templates", "defeat.bmp")):
        sys.exit("缺少 templates/defeat.bmp：先在战败结算界面用 mktpl.py 采一张")
    hwnd = hwnd_or_exit(cfg["window"]["title"], cfg["window"]["class"])
    for attempt in range(args.max):
        if attempt > 0:
            build_team(hwnd, cfg, attempt)
        if not wait_defeat(hwnd, cfg, args.timeout):
            print(f"第 {attempt + 1} 次：没有检测到战败（可能通关或已退出战斗）")
            continue
        # 战败后返回：优先配置的 back_btn，其次点中心
        back = cfg.get("back_btn")
        if back:
            tap(hwnd, back, 2.0)
        else:
            tap(hwnd, [960, 626], 2.0)
        time.sleep(2.0)
    print("达到重试上限，停止")


# ---------------- 升级 ----------------

def cmd_levelup(args) -> None:
    cfg = load_cfg()
    lv = cfg.get("levels") or {}
    if not lv.get("button"):
        sys.exit("team_config.json 里没有 levels.button")
    hwnd = hwnd_or_exit(cfg["window"]["title"], cfg["window"]["class"])
    times = args.times or int(lv.get("times", 3))
    for i in range(times):
        tap(hwnd, lv["button"], 1.0)
        print(f"升级点击 {i + 1}/{times}")
    print("升级结束（消耗金币/材料，已按次数上限停止）")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="BrownDust II")
    ap.add_argument("--class", dest="cls", default="UnityWndClass")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("calibrate")
    c.add_argument("--slot-step", type=int, default=150, help="槽位水平间距")
    c.add_argument("--roster-cols", type=int, default=6)
    c.add_argument("--roster-dx", type=int, default=95)
    c.add_argument("--roster-dy", type=int, default=100)
    c.set_defaults(func=cmd_calibrate)

    b = sub.add_parser("build")
    b.add_argument("--variant", type=int, default=0)
    b.set_defaults(func=cmd_build)

    r = sub.add_parser("retry")
    r.add_argument("--max", type=int, default=4)
    r.add_argument("--timeout", type=float, default=180)
    r.set_defaults(func=cmd_retry)

    u = sub.add_parser("levelup")
    u.add_argument("--times", type=int, default=0)
    u.set_defaults(func=cmd_levelup)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
