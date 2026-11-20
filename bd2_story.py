"""自动推进剧情主循环（通用模板版）。

配置驱动：每个锚点 = 模板 + 屏幕 ROI + 动作。
识别优先级按 anchors 数组顺序，命中第一个就执行它。

用法:
    python bd2_story.py --dry-run       # 只识别不点击
    python bd2_story.py                 # 正式运行
    python bd2_story.py --verbose       # 打印每个锚点分数
    F8 暂停/继续, F10 停止
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np
from PIL import Image

from bd2 import imgio, vision, win32

HERE_DIR = os.path.dirname(os.path.abspath(__file__))

VK_F8 = 0x77
VK_F10 = 0x79


def log(path: str, msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_anchor(a: dict) -> dict:
    tpl = imgio.read_bmp(a["tpl"])
    if tpl.ndim == 3:
        tpl = vision.gray(tpl)
    roi = tuple(int(v) for v in a["roi"])
    return {
        "name": a["name"],
        "tpl": tpl,
        "roi": roi,
        "thr": float(a.get("thr", 0.85)),
        "action": a.get("action", {"type": "none"}),
        "wait": float(a.get("wait", 1.2)),
        "cooldown": float(a.get("cooldown", a.get("wait", 1.2))),
    }


def send_key(vk: int) -> None:
    """向当前活动窗口发一次按键（F2 快进 / F3 倍速）。"""
    import ctypes
    u = ctypes.windll.user32
    u.keybd_event(vk, 0, 0, 0)
    time.sleep(0.05)
    u.keybd_event(vk, 0, 2, 0)


def do_action(
    a: dict,
    loc: tuple[int, int] | None,
    hwnd: int,
    w0: int,
    h0: int,
    cycle_state: dict[str, int],
) -> tuple[int, int] | None:
    act = a["action"]
    kind = act.get("type", "none")
    if kind == "cycle":
        pts = act["positions"]
        idx = cycle_state.get(a["name"], 0) % len(pts)
        cycle_state[a["name"]] = idx + 1
        px, py = int(pts[idx][0]), int(pts[idx][1])
        px = max(0, min(w0 - 1, px))
        py = max(0, min(h0 - 1, py))
        win32.click_client(hwnd, px, py)
        return px, py
    if kind == "key":
        send_key(int(act["vk"]))
        return act.get("pos") and (int(act["pos"][0]), int(act["pos"][1])) or None
    if kind != "click":
        return None
    pos = act.get("pos", "center")
    if pos == "center":
        px, py = w0 // 2, int(h0 * 0.58)
    elif pos == "match" and loc is not None:
        ox, oy = act.get("offset", [0, 0])
        px, py = loc[0] + ox, loc[1] + oy
    else:
        px, py = int(pos[0]), int(pos[1])
    px = max(0, min(w0 - 1, px))
    py = max(0, min(h0 - 1, py))
    win32.click_client(hwnd, px, py)
    return px, py


def ensure_game(title: str, cls: str, timeout: float = 180.0) -> int:
    """游戏没开就按官方协议拉起来，返回 hwnd。"""
    hwnd = win32.find_window(title, cls)
    if hwnd:
        return hwnd
    print("游戏未运行，正在启动官方启动器…")
    try:
        os.startfile("browndust2:games/10000002?usn=0")
    except Exception as exc:
        sys.exit(f"启动游戏失败: {exc}")
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        hwnd = win32.find_window(title, cls)
        if hwnd:
            print(f"游戏窗口已出现（{time.time()-t0:.0f}s）")
            time.sleep(8)    # 等 Logo / 资源校验
            return hwnd
    sys.exit("等待游戏窗口超时")


def pass_title(hwnd: int, w0: int, h0: int) -> None:
    """点掉 TOUCH TO START / 启动公告，尽量进到大厅。"""
    for i in range(4):
        win32.click_client(hwnd, w0 // 2, h0 // 2)
        time.sleep(6)


def enter_story(hwnd: int, w0: int, h0: int) -> bool:
    """大厅 → 剧情 → 主线播放。优先按画面文字找按钮，找不到再退回固定坐标。"""
    from story_ocr import locate

    def shot() -> np.ndarray:
        with win32.Grabber(hwnd) as g:
            time.sleep(0.5)
            return g.grab()

    frame = shot()
    # 0) 已经在剧情/剧情卡里（卡面上的按钮 OCR 常读成「主线05继续」）
    hit = locate(frame, ["主线播放", "播放剧情", "查看下一话"])
    if not hit:
        hit = locate(frame, ["主线"], y_min=600)
    if hit:
        win32.click_client(hwnd, hit[0], hit[1])
        time.sleep(3.0)
        return True
    # 1) 大厅底栏「剧情」图标（实测在 y≈1053，OCR 找字最稳）
    hit = locate(frame, ["剧情"], y_min=980)
    if hit:
        win32.click_client(hwnd, hit[0], hit[1])
        time.sleep(2.5)
        frame = shot()
    # 2) 剧情游戏卡里的「主线播放」
    hit = locate(frame, ["主线播放", "播放剧情"])
    if not hit:
        hit = locate(frame, ["播放", "开始"])
    if hit:
        win32.click_client(hwnd, hit[0], hit[1])
        time.sleep(3.0)
        return True
    # 找不到入口不瞎点：宁可等，也不要在大厅乱点一通
    return False


_MUTEX = None


def _single_instance(name: str = "BD2_STORY_ONE") -> bool:
    """同名互斥体，防止重复双击/多进程同时点同一个游戏（那是乱点的根源）。"""
    global _MUTEX
    import ctypes
    k32 = ctypes.windll.kernel32
    _MUTEX = k32.CreateMutexW(None, False, name)
    _MUTEX = ctypes.c_void_p(_MUTEX)
    if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print("已有本脚本在运行，本次退出（避免两个进程同时点）")
        return False
    return True


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not _single_instance():
        return

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--fps", type=float, default=0)
    ap.add_argument("--max-seconds", type=float, default=0)
    ap.add_argument("--no-launch", action="store_true", help="不自动打开游戏")
    ap.add_argument("--no-enter", action="store_true", help="不自动从大厅进入剧情")
    ap.add_argument("--no-digest", action="store_true", help="不读取对白文字（默认边跑边读）")
    ap.add_argument("--api-key", default="", help="OpenAI 兼容接口 Key（不给就只存台词）")
    ap.add_argument("--no-borderless", action="store_true", help="不改成无边框窗口")
    args = ap.parse_args()

    if not os.path.exists(args.config):
        sys.exit(f"找不到 {args.config}")

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    title = cfg["window"].get("title", "BrownDust II")
    cls = cfg["window"].get("class", "")
    hwnd = 0
    if not args.dry_run and not args.no_launch:
        hwnd = ensure_game(title, cls)
    if not hwnd:
        hwnd = win32.find_window(title, cls)
    if not hwnd:
        sys.exit("没有找到游戏窗口")

    _, _, w0, h0 = win32.client_rect(hwnd)
    expect = tuple(cfg.get("client", [w0, h0]))
    if (w0, h0) != expect:
        sys.exit(f"客户区是 {w0}x{h0}，配置是 {expect[0]}x{expect[1]}")

    anchors = [load_anchor(a) for a in cfg["anchors"]]
    fps = args.fps or float(cfg.get("fps", 2.0))
    k = int(cfg.get("downscale", 4))
    watchdog = cfg.get("watchdog", {})
    none_stop = float(watchdog.get("none_stop", 45))
    none_warn = float(watchdog.get("none_warn", 10))
    dark = cfg.get("dark")
    fallback = cfg.get("fallback") or {}
    fb_used = 0
    fb_last = 0.0
    blind = cfg.get("blind") or {}
    blind_used = 0
    blind_last = 0.0
    hotkey = cfg.get("hotkey") or {}
    hot_vk = int(hotkey.get("vk", 0) or 0)
    hot_interval = float(hotkey.get("interval", 3.0))
    hot_states = set(hotkey.get("states", ["story", "dark"]))
    hot_last = 0.0
    last_story_state = 0.0
    last_story_state = 0.0
    recover = cfg.get("recover") or {}
    recover_used = 0
    burst = cfg.get("burst") or {}
    digest = cfg.get("digest") or {}
    collector = None
    reader = None
    last_ocr = 0.0
    ocr_logged = 0
    last_popup_ocr = 0.0
    if not args.no_digest:
        from story_ocr import AsyncReader, Collector
        collector = Collector()
        reader = AsyncReader(collector)

    os.makedirs("logs", exist_ok=True)
    os.makedirs("debug", exist_ok=True)
    # 只留最近 30 个日志，避免长期跑把磁盘堆满
    try:
        olds = sorted(
            (os.path.join("logs", f) for f in os.listdir("logs") if f.endswith(".log")),
            key=os.path.getmtime,
        )[:-30]
        for f in olds:
            os.remove(f)
    except OSError:
        pass
    log_path = os.path.join("logs", time.strftime("story-%Y%m%d-%H%M%S.log"))
    log(log_path, f"启动 hwnd={hwnd} 客户区={w0}x{h0} fps={fps} dry={args.dry_run}")
    log(log_path, "锚点: " + ", ".join(a["name"] for a in anchors))

    if not args.dry_run and not win32.focus(hwnd):
        sys.exit("无法激活游戏窗口")

    # 无边框固定窗口：标题栏去掉后窗口=客户区，坐标不会再偏，也不会被拖动
    if not args.dry_run and not args.no_borderless:
        try:
            if not win32.is_borderless(hwnd):
                nw, nh = win32.set_borderless(hwnd, w0, h0)
                w0, h0 = nw, nh
                log(log_path, f"已设为无边框窗口，客户区 {w0}x{h0}")
                time.sleep(1.0)
        except Exception as exc:  # noqa: BLE001
            log(log_path, f"无边框设置失败: {exc}")

    # 已经处于剧情对话/黑屏转场就不动；否则从大厅点进剧情
    if not args.dry_run and not args.no_enter:
        with win32.Grabber(hwnd) as g0:
            time.sleep(1.0)
            probe = g0.grab()
        hit = None
        for a in anchors:
            s, loc = vision.find(probe, a["tpl"], a["roi"], k)
            if s >= a["thr"]:
                hit = (a["name"], s)
                break
        if hit:
            log(log_path, f"已在剧情内（{hit[0]} {hit[1]:.2f}），跳过进剧情")
        else:
            for attempt in range(3):
                log(log_path, f"未见剧情界面，尝试进剧情（第 {attempt+1} 次）")
                pass_title(hwnd, w0, h0)
                enter_story(hwnd, w0, h0)
                time.sleep(3)
                with win32.Grabber(hwnd) as g1:
                    probe = g1.grab()
                for a in anchors:
                    s, _ = vision.find(probe, a["tpl"], a["roi"], k)
                    if s >= a["thr"]:
                        hit = (a["name"], s)
                        break
                if hit:
                    log(log_path, f"进剧情成功（{hit[0]} {hit[1]:.2f}）")
                    last_story_state = time.time()
                    break
                # 没进去就退回大厅再试
                import ctypes
                u = ctypes.windll.user32
                u.keybd_event(0x1B, 0, 0, 0)
                time.sleep(0.05)
                u.keybd_event(0x1B, 0, 2, 0)
                time.sleep(2)

    state = ""
    state_since = time.time()
    last_click: dict[str, float] = {}
    none_since = time.time()
    debug_ts = 0.0
    debug_idx = 0
    paused = False
    f8_prev = f10_prev = False
    started = time.time()
    frames = 0
    period = 1.0 / max(fps, 0.2)
    cycle_state: dict[str, int] = {}
    last_hot = 0.0
    hotkey = cfg.get("hotkey") or {}

    try:
        with win32.Grabber(hwnd) as g:
            while True:
                t0 = time.perf_counter()
                f8, f10 = win32.key_down(VK_F8), win32.key_down(VK_F10)
                if f10 and not f10_prev:
                    log(log_path, "F10 停止")
                    break
                if f8 and not f8_prev:
                    paused = not paused
                    log(log_path, "暂停" if paused else "继续")
                f8_prev, f10_prev = f8, f10
                if paused:
                    time.sleep(0.2)
                    continue
                if args.max_seconds and time.time() - started > args.max_seconds:
                    log(log_path, "达到 --max-seconds")
                    break

                try:
                    frame = g.grab()
                except Exception as e:
                    log(log_path, f"截图失败: {e}")
                    time.sleep(0.5)
                    continue

                # 游戏切换场景偶尔会重建窗口样式，定期校验一下无边框
                if (
                    not args.dry_run
                    and not args.no_borderless
                    and frames % 200 == 0
                    and not win32.is_borderless(hwnd)
                ):
                    try:
                        w0, h0 = win32.set_borderless(hwnd, w0, h0)
                        log(log_path, f"窗口样式被重置，已重新设为无边框 {w0}x{h0}")
                    except Exception as exc:  # noqa: BLE001
                        log(log_path, f"重置无边框失败: {exc}")

                # F2 = 游戏内“快进/跳过”，剧情播放中每隔几秒按一次，比点按钮稳
                # 场景对话（气泡/无锚点）时 state 可能为空，只要最近读到过台词就仍按 F2
                if (
                    not args.dry_run
                    and hot_vk
                    and (
                        state in hot_states
                        or (not state and time.time() - last_story_state < 8)
                    )
                    and time.time() - hot_last > hot_interval
                ):
                    if win32.focus(hwnd):
                        send_key(hot_vk)
                        hot_last = time.time()
                        log(log_path, f"按键 F2 快进（状态 {state}）")

                # 直接读画面里的对白文字（后台线程，不停主循环）
                if (
                    reader is not None
                    and time.time() - last_ocr > float(digest.get("interval", 3.5))
                ):
                    last_ocr = time.time()
                    reader.submit(frame)
                if reader is not None and reader.added > ocr_logged:
                    ocr_logged = reader.added
                    last_story_state = time.time()
                    log(log_path, f"读到台词 +{reader.added}，累计 {len(collector.lines)} 行")

                hits = []
                found = None
                lum = float(vision.gray(frame[::4, ::4]).mean())
                dark_thr = float((dark or {}).get("luma", 14))
                is_dark = bool(dark) and lum <= dark_thr
                if not is_dark:
                    for a in anchors:
                        s, loc = vision.find(frame, a["tpl"], a["roi"], k)
                        if args.verbose:
                            hits.append(f"{a['name']}={s:.2f}")
                        if s >= a["thr"]:
                            found = (a, s, loc)
                            break

                frames += 1
                if args.verbose and frames % 5 == 0:
                    log(log_path, " ".join(hits))

                if found is None and is_dark:
                    now = time.time()
                    if (
                        not args.dry_run
                        and now - last_click.get("dark", 0) >= float(dark.get("cooldown", 4.0))
                    ):
                        if not win32.focus(hwnd):
                            log(log_path, "无法激活窗口，停止")
                            break
                        p = dark.get("pos", [1605, 945])
                        win32.click_client(hwnd, int(p[0]), int(p[1]))
                        last_click["dark"] = now
                        log(log_path, f"点击 dark @ ({p[0]}, {p[1]}) luma={lum:.1f}")
                    none_since = time.time()
                    last_story_state = time.time()
                    state = "dark"
                    time.sleep(float(dark.get("wait", 2.5)))
                    continue

                if found is None:
                    dur = time.time() - none_since
                    if (
                        fallback.get("points")
                        and fb_used < int(fallback.get("max", 2))
                        and dur > float(fallback.get("after", 15))
                        and time.time() - fb_last > float(fallback.get("cooldown", 15))
                    ):
                        if not args.dry_run:
                            if not win32.focus(hwnd):
                                log(log_path, "无法激活窗口，停止")
                                break
                            p = fallback["points"][0]
                            win32.click_client(hwnd, int(p[0]), int(p[1]))
                            fb_used += 1
                            fb_last = time.time()
                            log(log_path, f"点击 fallback @ ({p[0]}, {p[1]}) 已用 {fb_used}")
                        none_since = time.time()
                        time.sleep(2.0)
                        continue
                    # 新版（2.39.10）章节里会出现“场景内对话/镜头切换”，
                    # 没有任何锚点命中，但点屏幕中间就能推进，这类盲点要有上限地兜
                    if (
                        blind.get("points")
                        and blind_used < int(blind.get("max", 200))
                        and dur > float(blind.get("after", 8))
                        and time.time() - blind_last > float(blind.get("cooldown", 3))
                        and time.time() - last_story_state < 30
                    ):
                        if not args.dry_run:
                            if not win32.focus(hwnd):
                                log(log_path, "无法激活窗口，停止")
                                break
                            p = blind["points"][blind_used % len(blind["points"])]
                            win32.click_client(hwnd, int(p[0]), int(p[1]))
                            blind_used += 1
                            blind_last = time.time()
                            log(log_path, f"盲点推进 @ ({p[0]}, {p[1]}) 已用 {blind_used}")
                        none_since = time.time()
                        time.sleep(2.0)
                        continue
                    # 卡住时先截屏识图：结算「离开」、确认框这类按钮直接点掉
                    if dur > 6 and time.time() - last_popup_ocr > 6:
                        last_popup_ocr = time.time()
                        try:
                            from story_ocr import locate_exact as _loc
                            hit_pop = _loc(frame, ["确认", "确定", "关闭", "离开", "下一页", "确定离开", "返回"])
                        except Exception:
                            hit_pop = None
                        if not hit_pop:
                            # 卡面「主线00 继续」、战斗准备「开始战斗」、快进「跳过」这类短按钮
                            try:
                                from story_ocr import _boxes as _bx
                                for text, x1, y1, x2, y2 in _bx(frame):
                                    clean = text.replace(" ", "")
                                    if x2 - x1 > 420 or y1 < 200:
                                        continue
                                    if any(k in clean for k in ("开始战斗", "自动战斗", "继续", "跳过", "战斗开始")):
                                        hit_pop = ((x1 + x2) // 2, (y1 + y2) // 2, clean)
                                        break
                            except Exception:
                                pass
                        if hit_pop:
                            if win32.focus(hwnd):
                                win32.click_client(hwnd, hit_pop[0], hit_pop[1])
                                log(log_path, f"识图点按钮「{hit_pop[2]}」@ ({hit_pop[0]},{hit_pop[1]})")
                            none_since = time.time()
                            time.sleep(1.5)
                            continue
                    # 盲点连点多次仍无状态：多半卡在大厅/菜单，截屏识图后退回重进剧情
                    if (
                        recover.get("after")
                        and recover_used < int(recover.get("max", 6))
                        and (
                            blind_used >= int(recover.get("blind_triggers", 8))
                            or dur > float(recover.get("seconds", 12))
                        )
                    ):
                        recover_used += 1
                        log(log_path, f"{dur:.0f}s 无状态，尝试回大厅重进剧情（第 {recover_used} 次）")
                        texts: list[str] = []
                        try:
                            sp = os.path.join("debug", time.strftime("stuck-%H%M%S.bmp"))
                            imgio.write_bmp(sp, frame.copy())
                            log(log_path, f"已存卡住截图 {sp}")
                            from story_ocr import _boxes
                            texts = [t for t, *_ in _boxes(frame)]
                            log(log_path, "当前画面文字: " + " | ".join(texts[:8]))
                        except Exception as exc:  # noqa: BLE001
                            log(log_path, f"截图/识图失败: {exc}")
                        if not args.dry_run:
                            if not win32.focus(hwnd):
                                log(log_path, "无法激活窗口，停止")
                                break
                            # 公告/新闻界面：先按返回箭头，再关列表弹窗
                            if any("新闻" in t or "公告事项" in t for t in texts):
                                win32.click_client(hwnd, 42, 50)
                                log(log_path, "识图：关闭公告详情")
                                time.sleep(1.5)
                            elif sum("公告" in t for t in texts) >= 2:
                                win32.click_client(hwnd, 1358, 190)
                                log(log_path, "识图：关闭公告列表")
                                time.sleep(1.5)
                            else:
                                send_key(0x1B)
                                time.sleep(1.5)
                            enter_story(hwnd, w0, h0)
                        none_since = time.time()
                        blind_used = 0
                        time.sleep(2.0)
                        continue
                    if dur > none_warn and time.time() - debug_ts > 8:
                        path = os.path.join("debug", f"none-{debug_idx % 5}.bmp")
                        imgio.write_bmp(path, frame.copy())
                        debug_idx += 1
                        debug_ts = time.time()
                        log(log_path, f"{dur:.0f}s 无已知状态，已存 {path}")
                    if dur > none_stop:
                        log(log_path, f"{dur:.0f}s 无已知状态，停止")
                        break
                    time.sleep(max(0.0, period - (time.perf_counter() - t0)))
                    continue

                none_since = time.time()
                last_story_state = time.time()
                a, s, loc = found
                if a["name"] != state:
                    log(log_path, f"状态 {state or '-'} -> {a['name']} ({s:.2f})")
                    state = a["name"]
                    state_since = time.time()

                if not args.dry_run:
                    if time.time() - last_click.get(a["name"], 0) >= a["cooldown"]:
                        if not win32.focus(hwnd):
                            log(log_path, "无法激活窗口，停止")
                            break
                        p = do_action(a, loc, hwnd, w0, h0, cycle_state)
                        last_click[a["name"]] = time.time()
                        if p:
                            log(log_path, f"点击 {a['name']} @ {p} ({s:.2f})")
                        # 对白段落不每帧都截图：连点几下再回去识别，速度能翻倍
                        if a["name"] == "story" and int(burst.get("clicks", 0)):
                            for _ in range(int(burst["clicks"])):
                                time.sleep(float(burst.get("interval", 0.6)))
                                win32.click_client(hwnd, p[0], p[1])
                    time.sleep(a["wait"])
                else:
                    time.sleep(0.3)
    except KeyboardInterrupt:
        log(log_path, "Ctrl+C")
    finally:
        log(log_path, f"结束 共 {frames} 帧")
        if reader is not None:
            reader.close()
        if collector is not None and collector.lines:
            stamp = time.strftime("%Y%m%d-%H%M")
            tpath = os.path.join(HERE_DIR, f"台词-{stamp}.md")
            with open(tpath, "w", encoding="utf-8") as f:
                f.write("# 剧情台词（边跑边读）\n\n" + collector.text() + "\n")
            log(log_path, f"台词 {len(collector.lines)} 行 -> {tpath}")
            # 只留最近 10 份台词，避免堆积
            try:
                olds = sorted(
                    (os.path.join(HERE_DIR, f) for f in os.listdir(HERE_DIR)
                     if f.startswith("台词-") and f.endswith(".md")),
                    key=os.path.getmtime,
                )[:-10]
                for f in olds:
                    os.remove(f)
            except OSError:
                pass
            api = dict(cfg.get("api") or {})
            if args.api_key:
                api["key"] = args.api_key
            if api.get("key"):
                try:
                    from story_ocr import summarize
                    spath = os.path.join(HERE_DIR, f"剧情梗概-{stamp}.md")
                    summarize(collector.lines, api, spath)
                    log(log_path, f"梗概 -> {spath}")
                except Exception as exc:  # noqa: BLE001
                    log(log_path, f"梗概生成失败: {exc}")


if __name__ == "__main__":
    main()
