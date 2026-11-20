"""收益账本：每跑完一个任务记一行「前/后货币」，跑完勾选项后生成当日日报。

只做三件事：
1) 追加 JSONL 账本  debug\\ledger-YYYYMMDD.jsonl
2) 汇总成 markdown 收益日报-YYYYMMDD.md（收益=涨的，花费=跌的）
3) 可选把游戏任务页的 0/1、1/1 一起抓进日报（不花钱、不点任何按钮，只读）
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEBUG = os.path.join(HERE, "debug")

LABELS = {
    "story": "自动剧情", "rewards": "任务页领奖", "daily": "日常任务", "weekly": "周常任务",
    "mail": "邮件", "pass": "通行证", "guest": "亲密度谈心", "gueststory": "有缘之客剧情",
    "quick": "快速狩猎", "freegacha": "免费抽抽乐", "collect": "地图采集", "arbitrage": "商店套利",
    "equip": "装备制作", "activity": "活动", "full": "日常全量", "session": "整队合计",
    "extra": "其它",
}


def _date(ts: float | None = None) -> str:
    return time.strftime("%Y%m%d", time.localtime(ts or time.time()))


def ledger_path(date: str | None = None) -> str:
    os.makedirs(DEBUG, exist_ok=True)
    return os.path.join(DEBUG, f"ledger-{date or _date()}.jsonl")


def report_path(date: str | None = None) -> str:
    return os.path.join(HERE, f"收益日报-{date or _date()}.md")


def append(task: str, before: dict | None, after: dict | None,
           dur: float = 0, ok: bool = True, note: str = "", ts: float | None = None) -> str:
    row = {
        "ts": time.strftime("%H:%M:%S", time.localtime(ts or time.time())),
        "date": _date(ts),
        "task": task,
        "label": LABELS.get(task, task),
        "dur": round(dur, 1),
        "ok": bool(ok),
        "before": before or {},
        "after": after or {},
        "note": note,
    }
    with open(ledger_path(row["date"]), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row["date"]


def load(date: str | None = None) -> list[dict]:
    p = ledger_path(date)
    if not os.path.exists(p):
        return []
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def _delta(before: dict, after: dict, key: str) -> int | None:
    b, a = (before or {}).get(key), (after or {}).get(key)
    if b is None or a is None:
        return None
    if a > b * 3 or a < b / 3:  # OCR 多/少一位的抖动，一律当没读到
        return None
    return a - b


def _fmt(v: int | None, sign: bool = True) -> str:
    if v is None:
        return "—"
    if not sign:
        return f"{v:,}"
    return f"+{v:,}" if v > 0 else f"{v:,}" if v == 0 else f"-{abs(v):,}"


def build_report(date: str | None = None, account: dict | None = None) -> str:
    date = date or _date()
    rows = load(date)
    if not rows:
        return ""

    task_rows = [r for r in rows if r["task"] != "session"]
    first_before = next((r["before"] for r in task_rows if r["before"]), None)
    last_after = next((r["after"] for r in reversed(task_rows) if r["after"]), None)
    if account:
        first_before = first_before or account.get("before")
        last_after = last_after or account.get("after")

    lines = [f"# 棕色尘埃2 · 收益日报 {date[:4]}-{date[4:6]}-{date[6:]}", ""]
    if first_before and last_after:
        lines.append("**账号总账**：钻石 {}（{}）　付费钻 {}（{}）　金币 {}（{}）".format(
            _fmt(last_after.get("diamond"), False), _fmt(_delta(first_before, last_after, "diamond")),
            _fmt(last_after.get("paid"), False), _fmt(_delta(first_before, last_after, "paid")),
            _fmt(last_after.get("gold"), False), _fmt(_delta(first_before, last_after, "gold")),
        ))
    else:
        lines.append("**账号总账**：本轮货币读数不全，以下按逐项差值统计。")
    lines.append("")

    lines.append("## 逐项明细")
    lines.append("")
    lines.append("| 时间 | 任务 | 用时 | 结果 | 钻石 | 付费钻 | 金币 | 备注 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in task_rows:
        b, a = r.get("before") or {}, r.get("after") or {}
        lines.append("| {} | {} | {}s | {} | {} | {} | {} | {} |".format(
            r.get("ts", ""), r.get("label", r["task"]), int(r.get("dur") or 0),
            "成功" if r.get("ok") else "失败/中断",
            _fmt(_delta(b, a, "diamond")), _fmt(_delta(b, a, "paid")),
            _fmt(_delta(b, a, "gold")), (r.get("note") or "").replace("|", "/"),
        ))
    lines.append("")

    if first_before and last_after:
        d_dia = _delta(first_before, last_after, "diamond") or 0
        d_paid = _delta(first_before, last_after, "paid") or 0
        d_gold = _delta(first_before, last_after, "gold") or 0
        gains = []
        if d_paid > 0:
            gains.append(f"付费钻石 +{d_paid:,}")
        if d_gold > 0:
            gains.append(f"金币 +{d_gold:,}")
        if d_dia > 0:
            gains.append(f"钻石 +{d_dia:,}（来源不是本工具消费）")
        costs = []
        if d_dia < 0:
            costs.append(f"钻石 {d_dia:,}")
        if d_paid < 0:
            costs.append(f"付费钻石 {d_paid:,}")
        if d_gold < 0:
            costs.append(f"金币 {d_gold:,}")
        if d_dia == 0:
            costs.append("钻石 0（全程没花一颗）")
        if not costs:
            costs.append("本轮没有货币支出")
        lines.append("## 今日收益")
        for g in (gains or ["本轮没有货币进账（收益可能是任务点/材料，见逐项结果）"]):
            lines.append(f"- {g}")
        lines.append("")
        lines.append("## 今日花费")
        for c in costs:
            lines.append(f"- {c}")
        lines.append("")

    done = [r for r in task_rows if r.get("ok")]
    miss = [r for r in task_rows if not r.get("ok")]
    lines.append("## 跑了几项")
    lines.append(f"- 成功 {len(done)} 项：{'、'.join(r['label'] for r in done) or '无'}")
    if miss:
        lines.append(f"- 未完成 {len(miss)} 项：{'、'.join(r['label'] for r in miss)}")
    lines.append("")

    p = report_path(date)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return p


def read_task_page() -> list[str]:
    """只读抓游戏任务页的完成度（打不开就返回空，不硬点）。"""
    try:
        import sys as _sys
        _sys.path.insert(0, HERE)
        import bd2_auto_daily as daily
        from bd2 import win32
        hwnd = win32.find_window("BrownDust II", "UnityWndClass")
        if not hwnd or not daily.at_lobby(hwnd):
            return []
        win32.focus(hwnd)
        win32.click_client(hwnd, 682, 1022)
        time.sleep(2.0)
        from story_ocr import _boxes
        with win32.Grabber(hwnd) as g:
            f = g.grab()
        texts = [t for t, *_ in _boxes(f)]
        import re as _re
        out = [t for t in texts
               if _re.search(r"\d+\s*[/／]\s*\d+", t) and not t.startswith("FPS") and len(t) <= 30]
        win32.click_client(hwnd, 80, 62)
        return out
    except Exception:
        return []


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--account", action="store_true", help="把整队前/后货币也记一行")
    ap.add_argument("--task-page", action="store_true", help="日报附上游戏任务页完成度")
    args = ap.parse_args()
    date = _date()

    if args.account:
        import bd2_guard as guard
        from bd2 import win32
        hwnd = win32.find_window("BrownDust II", "UnityWndClass")
        cur = guard.read_currency(hwnd) if hwnd else {}
        print(json.dumps(cur, ensure_ascii=False))
        return 0

    if not args.report:
        ap.print_help()
        return 0

    p = build_report(date)
    if not p:
        print("今天还没有账本记录")
        return 1
    if args.task_page:
        items = read_task_page()
        if items:
            with open(p, "a", encoding="utf-8") as f:
                f.write("## 游戏任务页完成度\n\n")
                for it in items:
                    f.write(f"- {it}\n")
                f.write("\n")
    print(p)
    if args.open:
        os.startfile(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
