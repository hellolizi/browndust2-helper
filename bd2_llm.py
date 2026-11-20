"""本机侧的大模型调用（OpenAI 兼容），只负责"需要脑子"的几步

设计原则：
  1. 没有 Key 或调用失败 → 立刻回落到确定性规则，绝不卡住游戏流程
  2. 每次只发必要文本（场景 + 选项），不传截图，省 token / 省显存
  3. 超时 12s，失败即回落；同一个问题一天内只问一次（落盘缓存）

配置：config.json 里 "api": {"key": "...", "base": "https://api.deepseek.com/v1", "model": "deepseek-chat"}

用法：
    from bd2_llm import decide
    idx = decide("席比雅问香草怎么处理", "多余新芽怎么处理？", ["拔了扔掉。", "移栽到别的地方。"])
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "debug", "llm-cache.json")


def _cfg() -> dict:
    try:
        cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
        return cfg.get("api", {}) or {}
    except Exception:
        return {}


def available() -> bool:
    return bool((_cfg().get("key") or "").strip())


def _cache_get(key: str):
    try:
        d = json.load(open(CACHE, encoding="utf-8"))
        e = d.get(key)
        if e and time.time() - e.get("t", 0) < 86400:
            return e.get("v")
    except Exception:
        pass
    return None


def _cache_put(key: str, val) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        d = {}
        if os.path.isfile(CACHE):
            d = json.load(open(CACHE, encoding="utf-8"))
        d[key] = {"t": time.time(), "v": val}
        # 只留最近 500 条，防止文件越来越大
        if len(d) > 500:
            d = dict(sorted(d.items(), key=lambda kv: kv[1].get("t", 0))[-500:])
        json.dump(d, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def _chat(system: str, user: str, max_tokens: int = 80, temperature: float = 0.1) -> str:
    c = _cfg()
    key = (c.get("key") or "").strip()
    if not key:
        raise RuntimeError("no key")
    base = (c.get("base") or "https://api.deepseek.com/v1").rstrip("/")
    model = c.get("model") or "deepseek-chat"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
    })
    with urllib.request.urlopen(req, timeout=12) as r:
        data = json.loads(r.read().decode())
    return data["choices"][0]["message"]["content"]


def decide(scene: str, question: str, options: list[str]) -> int:
    """[LLM] 选"对方想听的"那个选项（亲密度拿满经验）。失败返回 0。"""
    if len(options) <= 1:
        return 0
    h = "d:" + hashlib.md5((scene + "|" + question + "|" + "|".join(options)).encode()).hexdigest()[:12]
    c = _cache_get(h)
    if isinstance(c, int):
        return c
    if not available():
        return 0
    sys_p = ("你在玩《棕色尘埃2》。游戏给出两个对话选项，只有一个能让角色好感经验拿满。"
             "判断哪个是对方最想听的。只输出 JSON：{\"index\":0}")
    usr = f"场景：{scene}\n问题：{question}\n选项：" + "\n".join(f"{i}. {o}" for i, o in enumerate(options))
    try:
        raw = _chat(sys_p, usr, 60)
        idx = int(json.loads(raw[raw.find("{"):raw.rfind("}") + 1]).get("index", 0))
        if not 0 <= idx < len(options):
            idx = 0
        _cache_put(h, idx)
        return idx
    except Exception:
        return 0


def summary(title: str, lines: list[str]) -> str:
    """[LLM] 台词 → 150 字梗概。失败返回空串。"""
    if not available() or not lines:
        return ""
    try:
        return _chat("把游戏剧情对白压缩成 150 字以内中文梗概，保留人名与关键转折，不要评论。",
                     f"标题：{title}\n" + "\n".join(lines[:200]), 400, 0.3).strip()
    except Exception:
        return ""


if __name__ == "__main__":
    print("key 已配置：" if available() else "key 未配置（会全程走规则回落）")
    print("自测选项判定：", decide("测试", "选哪个？", ["随便应付", "认真回应"]))
