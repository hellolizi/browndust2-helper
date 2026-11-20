"""把剧情截图 OCR 成台词文本，再（可选）调 API 生成梗概。

用法：
    python story_digest.py --shots shots            # 只 OCR，输出 transcript.md
    python story_digest.py --shots shots --api      # 调 config 里的 api 生成梗概

config.json 里可选：
    "api": {"base_url": "https://api.deepseek.com/v1", "key": "sk-...",
            "model": "deepseek-chat", "lang": "zh"}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

from PIL import Image

CROP = (150, 770, 1780, 1015)   # 1920x1080 下对白框大致区域


def ocr_lines(path: str, engine) -> list[str]:
    """整帧 OCR：气泡对话与底部对白都在画面里，避免只裁底部漏掉气泡场景。"""
    im = Image.open(path).convert("RGB")
    im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
    out, _ = engine(__import__("numpy").array(im))
    if not out:
        return []
    noise = (
        "fps", "gpu", "cpu", "延迟", "browndust", "n/a", "×3", "f2", "f3",
        "q搜发", "未解锁", "查看下一话", "主线播放", "集数列表", "游戏卡",
        "赛季活动", "日常剧情", "年代记", "术语", "原作",
    )
    ui_time = re.compile(r"^(下?年|下?午)\s?\d{1,4}$")
    lines = []
    for item in out:
        text = str(item[1]).strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) < 2:
            continue
        if not re.search(r"[\u4e00-\u9fff]", text):
            continue
        if any(n in text.lower() for n in noise):
            continue
        if ui_time.match(text):
            continue
        lines.append(text)
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="shots")
    ap.add_argument("--out", default="transcript.md")
    ap.add_argument("--api", action="store_true")
    args = ap.parse_args()

    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()

    shots = sorted(
        os.path.join(args.shots, f)
        for f in os.listdir(args.shots)
        if f.lower().endswith((".png", ".bmp", ".jpg"))
    )
    if not shots:
        sys.exit("没有截图")

    seen: list[str] = []
    for i, p in enumerate(shots, 1):
        for line in ocr_lines(p, engine):
            if not seen or line != seen[-1]:
                seen.append(line)
        if i % 10 == 0:
            print(f"{i}/{len(shots)}")

    body = "\n".join(f"- {s}" for s in seen)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# 剧情台词（OCR）\n\n" + body + "\n")
    print(f"台词 {len(seen)} 行 -> {args.out}")

    if not args.api:
        return
    with open("config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    api = cfg.get("api") or {}
    if not api.get("key"):
        sys.exit("config.json 里没有 api.key")

    prompt = (
        "下面是一段游戏主线剧情的逐句 OCR 台词，可能有错字和重复。"
        "请整理成中文剧情梗概：按场景分段，保留人物名和关键事件，"
        "去掉 OCR 噪音，最后给一段 100 字以内的总述。\n\n" + "\n".join(seen)
    )
    data = json.dumps({
        "model": api.get("model", "deepseek-chat"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        api["base_url"].rstrip("/") + "/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api["key"]},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
    text = resp["choices"][0]["message"]["content"]
    with open("story-summary.md", "w", encoding="utf-8") as f:
        f.write("# 剧情梗概（AI 生成）\n\n" + text + "\n")
    print("梗概 -> story-summary.md")


if __name__ == "__main__":
    main()
