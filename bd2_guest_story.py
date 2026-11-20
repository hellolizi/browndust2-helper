"""有缘之客（Fated Guest）剧情自动过 —— 只看不动钱包

流程：
  大厅 → 亲密度 → 逐个角色卡进详情页 → 把每个「来访 N」后面亮着的「播放」点开
  → 剧情里自动点屏/按 F2 快进 → 回到详情页 → 下一个角色 → 退场

硬约束：全程只点击「播放」与剧情对话区，绝不碰任何购买/兑换按钮（钻石 0 消耗）。
产物：台词-有缘之客-<时间>.md（按角色分节，带台词行）

用法：
  python bd2_guest_story.py             # 自动过
  python bd2_guest_story.py --dry       # 只扫描，不点播放
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from bd2 import win32  # noqa: E402
import bd2_llm  # noqa: E402
from story_ocr import _boxes, lines_from_frame  # noqa: E402

GAME = ("BrownDust II", "UnityWndClass")
# 大厅 / 亲密度页固定坐标（1920×1080 实测）
LOBBY_INTIMACY = (362, 303)
PLAY_X = 1746          # 详情页「播放」按钮所在竖列
BACK_BTN = (80, 62)    # 详情页左上返回
DETAIL_TOP_Y = 250     # 详情页顶部角色名大致高度

MAX_EPISODES_PER_CHAR = 12
EPISODE_TIMEOUT = 75
LOBBY_WAIT = 12


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def send_vk(vk: int) -> None:
    u = ctypes.windll.user32
    u.keybd_event(vk, 0, 0, 0)
    time.sleep(0.04)
    u.keybd_event(vk, 0, 2, 0)


def ocr_texts(hwnd: int) -> tuple[list[str], list[tuple[str, int, int, int, int]]]:
    with win32.Grabber(hwnd) as g:
        f = g.grab()
    boxes = _boxes(f)
    return [b[0] for b in boxes], boxes


def click(hwnd: int, x: int, y: int, wait: float = 1.2) -> None:
    win32.click_client(hwnd, x, y)
    time.sleep(wait)


def to_lobby(hwnd: int) -> bool:
    """尽量回到大厅：先按 ESC，再点可能存在的返回/关闭，最后验证底栏。

    层级：剧情/详情 → 亲密度格页 → 大厅，每层都要 ESC 或点返回。
    """
    for _ in range(6):
        texts, boxes = ocr_texts(hwnd)
        if any("抽抽乐" in t or "珍藏集" in t for t in texts):
            return True
        # 实测：这游戏的 ESC 在详情页无效，左上角的返回箭头才通吃两层
        click(hwnd, *BACK_BTN, 1.1)
        texts, _ = ocr_texts(hwnd)
        if any("抽抽乐" in t or "珍藏集" in t for t in texts):
            return True
    return False


def open_intimacy(hwnd: int) -> bool:
    click(hwnd, *LOBBY_INTIMACY, 1.6)
    texts, _ = ocr_texts(hwnd)
    return any("亲密度" in t for t in texts) and any("谈心" in t or "来袭" in t or "来访" in t for t in texts)


def character_slots(hwnd: int) -> list[tuple[int, int, str]]:
    """亲密度主页的角色卡：名字框上方 ~52px 就是卡面中心。返回 (点击x, 点击y, 角色名)。"""
    texts, boxes = ocr_texts(hwnd)
    slots: list[tuple[int, int, str]] = []
    for t, x1, y1, x2, y2 in boxes:
        if not (300 <= y1 <= 900):
            continue
        if len(t) < 2 or len(t) > 8:
            continue
        if any(k in t for k in ("LV", "未拥有", "%", "亲密度", "谈心", "来访", "赠送")):
            continue
        cx, cy = (x1 + x2) // 2, y2 - 52
        if cy < 220:
            continue
        if any(abs(cx - px) < 40 and abs(cy - py) < 40 for px, py, _ in slots):
            continue
        slots.append((cx, cy, t))
    return slots


def open_detail(hwnd: int, x: int, y: int, fallback_name: str) -> str | None:
    """点角色卡，判断是否进到有「来访」列表的详情页；成功返回角色名。

    详情页顶部大标题就是角色名，比列表页 OCR 出来的一串更准。
    """
    click(hwnd, x, y, 1.5)
    texts, boxes = ocr_texts(hwnd)
    if not any("来访" in t for t in texts):
        return None
    ui = ("亲密度", "亲密度增益", "谈心", "快速谈心", "赠送礼物", "来访", "播放", "未解锁", "剧情", "记录")
    for t, x1, y1, x2, y2 in boxes:
        if y1 > 230:
            continue
        if not (2 <= len(t) <= 8) or any(k in t for k in ui):
            continue
        if "LV" in t or "%" in t:
            continue
        return t
    return fallback_name


def play_row_y(texts: list[str], boxes: list[tuple[str, int, int, int, int]]) -> list[int]:
    """详情页里每个亮着的「播放」按钮的 y。"""
    ys = sorted({(y1 + y2) // 2 for t, x1, y1, x2, y2 in boxes if t.replace(" ", "") == "播放"})
    return ys


def ensure_full(hwnd: int) -> None:
    """切屏/换显示器会把窗口甩到屏幕外，抓图只剩黑边，这里拉回全屏。"""
    try:
        x, y, w, h = win32.client_rect(hwnd)
        if (w, h) != (1920, 1080) or abs(x) > 8 or abs(y) > 40:
            win32.set_borderless(hwnd, 1920, 1080)
            log(f"窗口被挪走 {(x, y, w, h)}，已拉回全屏")
    except Exception:
        pass


def watch_episode(hwnd: int, y: int, collector: list[str]) -> bool:
    """点一次播放，然后一路点屏 + F2 直到回到详情页。"""
    click(hwnd, PLAY_X, y, 1.3)
    t0 = time.time()
    saw_dialogue = False
    tick = 0
    while time.time() - t0 < EPISODE_TIMEOUT:
        tick += 1
        if tick % 5 == 0:
            ensure_full(hwnd)
        try:
            with win32.Grabber(hwnd) as g:
                f = g.grab()
            boxes = _boxes(f)
            texts = [b[0] for b in boxes]
            lines = lines_from_frame(f)
        except Exception:
            boxes, texts, lines = [], [], []
        if any("来访" in t for t in texts) and any("播放" in t or "未解锁" in t for t in texts):
            if time.time() - t0 > 3:
                return saw_dialogue
        # [LLM] 有分支选项时问一次模型"对方想听哪个"，没 Key 就选第一个（不亏但不满经验）
        opts = [(t, (x1 + x2) // 2, (y1 + y2) // 2) for t, x1, y1, x2, y2 in boxes
                if y1 >= 520 and y2 <= 780 and len(t) >= 4 and x2 - x1 >= 220]
        if len(opts) >= 2:
            idx = bd2_llm.decide("有缘之客来访剧情选项", "选哪个更合适？", [o[0] for o in opts[:3]])
            pick = opts[min(idx, len(opts) - 1)]
            log(f"    选项{len(opts)} 个，选第 {idx + 1} 个：{pick[0][:18]}")
            win32.click_client(hwnd, pick[1], pick[2])
            time.sleep(1.4)
            continue
        if lines:
            saw_dialogue = True
            for ln in lines:
                if ln not in collector:
                    collector.append(ln)
        send_vk(0x71)  # F2 快进剧情
        win32.click_client(hwnd, 960, 620)
        time.sleep(1.1)
    log(f"  ! 单集超过 {EPISODE_TIMEOUT}s，强行退出")
    return saw_dialogue


def leave_detail(hwnd: int) -> None:
    click(hwnd, *BACK_BTN, 1.1)
    texts, _ = ocr_texts(hwnd)
    if any("来访" in t for t in texts):
        send_vk(0x1B)
        time.sleep(0.9)


def run(dry: bool = False, out_path: str | None = None) -> int:
    hwnd = win32.find_window(*GAME)
    if not hwnd:
        log("没找到游戏窗口")
        return 2
    win32.focus(hwnd)
    time.sleep(0.5)
    win32.set_borderless(hwnd, 1920, 1080)
    time.sleep(0.4)

    if not to_lobby(hwnd):
        log("回不到大厅，放弃（先手动回大厅或跑 Global_ToHomePage）")
        return 3
    if not open_intimacy(hwnd):
        log("打不开亲密度页（可能还停在别的界面）")
        return 4
    log("已进入亲密度页")

    slots = character_slots(hwnd)
    log(f"识别到 {len(slots)} 个角色卡位")
    today = time.strftime("%Y%m%d")
    state_path = os.path.join(HERE, "debug", f"guest_seen-{today}.json")
    seen: dict[str, list[int]] = {}
    if os.path.isfile(state_path):
        try:
            import json
            seen = json.load(open(state_path, encoding="utf-8"))
        except Exception:
            seen = {}
    resume: dict[str, list[str]] = {}
    for idx, (x, y, card_name) in enumerate(slots, 1):
        if idx % 4 == 1:
            ensure_full(hwnd)
        name = open_detail(hwnd, x, y, card_name)
        if not name:
            continue
        texts, boxes = ocr_texts(hwnd)
        plays = play_row_y(texts, boxes)
        todo = [py for py in plays if py not in seen.get(name, [])]
        if not todo:
            why = "今天已经全看过了" if plays else "没有可播放的来访（未解锁或需先谈心）"
            log(f"[{idx}] {name}：{why}")
            leave_detail(hwnd)
            continue
        log(f"[{idx}] {name}：{len(todo)} 段待看（共 {len(plays)} 段可播）{todo}")
        if dry:
            leave_detail(hwnd)
            continue
        lines: list[str] = []
        for pid, py in enumerate(todo, 1):
            ok = watch_episode(hwnd, py, lines)
            log(f"    第{pid} 段结束（对白 {'有' if ok else '无'}，累计 {len(lines)} 行）")
            seen.setdefault(name, []).append(py)
            time.sleep(0.6)
            leave_detail_reopen(hwnd, x, y)
        if lines:
            resume[name] = lines
            # 每看完一个角色就落盘，防止中途被打断白干
            append_md(out_path, name, lines)
        try:
            import json
            json.dump(seen, open(state_path, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
        leave_detail(hwnd)
        time.sleep(0.5)

    log(f"有缘之客剧情处理完成（本次 {len(resume)} 个角色有新台词）")
    to_lobby(hwnd)   # 别把游戏丢在详情页，方便下一个任务直接开跑
    return 0


def append_md(out_path: str | None, name: str, lines: list[str]) -> None:
    if not out_path:
        return
    day = time.strftime("%Y%m%d")
    path = out_path.format(day=day)
    new = not os.path.isfile(path)
    with open(path, "a", encoding="utf-8") as fh:
        if new:
            fh.write(f"# 有缘之客 来访剧情台词 {day}\n\n")
        fh.write(f"## {name}\n\n")
        for ln in lines:
            fh.write(f"- {ln}\n")
        fh.write("\n")
    log(f"  台词已追加到 {os.path.basename(path)}")


def leave_detail_reopen(hwnd: int, x: int, y: int) -> None:
    """播完一集后会回到详情页；如果被弹回列表就重新点进去。"""
    texts, _ = ocr_texts(hwnd)
    if any("来访" in t for t in texts):
        return
    for _ in range(2):
        send_vk(0x1B)
        time.sleep(0.8)
        texts, _ = ocr_texts(hwnd)
        if any("来访" in t for t in texts):
            return
    click(hwnd, x, y, 1.4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只扫描不播放")
    ap.add_argument("--out", default=os.path.join(HERE, "台词-有缘之客-{day}.md"))
    args = ap.parse_args()
    return run(args.dry, args.out)


if __name__ == "__main__":
    sys.exit(main())
