# Brown Dust 2 auto helper

A screen-reading bot for the PC client of Brown Dust 2 (1920x1080, borderless). It grabs frames with Win32, matches a handful of templates, and clicks. No DLL injection, no memory reading, no packet sniffing.

I wrote it for my own account. Three things annoyed me. The daily routine is the same twelve taps every morning. The weekly list hides a story segment that stalls any naive macro. Every public bot I found handles dailies but stops at "now go read the story yourself".

## What it runs

The task list is checkboxes, not a fixed script. Pick what you want, it runs them in order and stops when something breaks.

| Key | What it does | Time on my machine |
|---|---|---|
| `daily` | full daily routine | 96s |
| `weekly` | weekly list, story segments included | 162s, 56 story skips |
| `rewards` | claims daily and weekly milestone rewards | 39s |
| `mail` / `pass` | mailbox and season pass | 25s / 32s |
| `gueststory` | replays every visiting-guest cutscene | about 9 min for 5 characters |
| `quick` | quick hunts | 86s |
| `freegacha` | the free draw that counts for the daily quest | 64s |

Anything that spends premium currency stays out. The activity page has a paid-diamond exchange inside it, so `Activity_Start` is blocked in the wrapper itself rather than just unchecked by default.

The heavy lifting for dailies is [MFABD2](https://github.com/sunyink/MFABD2), a MaaFramework pipeline. This repo drives it, watches the screen while it runs, and adds the parts it does not do: story advancement, guest cutscenes, and a currency check around every step.

## The part I actually care about

I have 8,074 free diamonds and I want to keep all of them.

`bd2_guard.py` OCRs three boxes in the lobby top bar: diamonds, gold, paid diamonds. The wrapper reads them before and after every task and aborts the whole queue if either diamond counter drops. Gold is allowed to move, since arbitrage spends it.

Two things I got wrong at first and had to fix:

- The top bar moves between screens. Reading it while standing in the quick-hunt screen once returned the paid-diamond number as the free-diamond number, which looked like a 30,000 diamond loss. So the guard walks back to the lobby first, and if it cannot get there it skips the check instead of reporting a failure.
- OCR sometimes swallows a neighbouring glyph, turning 26,019,346 into 2,601,919,346. Digits past a sane length are treated as unreadable rather than compared.

Result after a full evening of runs: 8,074 before, 8,074 after. The guard never fired.

## How the story part works

The story screen has an F2 fast-forward icon in the top right. Matching that icon is a more reliable "am I inside a cutscene" test than matching a specific dialogue scene, because it survives scene changes. When it hits, the bot presses F2 and then clicks the centre of the screen to advance. Branch choices are read with OCR: when two or more text lines sit in the choice band, the first option gets clicked.

Black transitions are handled by brightness, not templates. Below luma 14 it clicks the next spot. Template matching on a black screen gives false positives on loading screens.

## Guest cutscenes

Visiting-guest stories are not a menu. You open the intimacy page, infer each character card centre from the name plate above it, open the detail page, then click the play button in the visit list. The script walks that path, records the dialogue it sees into a markdown file, and tracks what it already watched for the day so a re-run does not spin.

Five characters, fifteen segments, nine minutes, and it never touched the daily visit count. Those segments are replays and cost nothing.

## Daily report

Every run appends before/after currency to `debug/ledger-YYYYMMDD.jsonl` and writes `收益日报-YYYYMMDD.md`: per-task deltas, total gain, total spend, and the daily and weekly checklist read off the in-game task page. Diamonds are kept separate from gold so a zero-diamond day is obvious at a glance.

## Setup

Python 3.10+ (I use 3.13), numpy, Pillow. OCR runs on an ONNX model through `rapidocr_onnxruntime`, capped at two threads so it does not eat the whole CPU while the game is running.

```powershell
pip install -r requirements.txt
python selftest.py
python bd2_story.py --dry-run --verbose --max-seconds 10
python bd2_launcher.py
```

The game window must be `BrownDust II` with class `UnityWndClass` and a 1920x1080 client area. Story mode needs you to be past the title screen once; the script can launch the client through the `browndust2:` protocol itself.

For the `daily`, `weekly` and `quick` tasks you also need MFABD2 checked out next to this folder, or `BD2_TOOLS` pointing at it.

## Known rough edges

- 1920x1080 only. Every ROI is a hard-coded absolute coordinate. 2K or windowed mode will not work.
- Something on this machine moves the game window every few minutes. The wrapper puts it back, but only after two consecutive odd readings, otherwise it interrupts loading screens.
- The restaurant revenue popup reappears over the lobby and covers the bottom bar. It gets dismissed with collect-all or cancel. Nothing else on that popup is clicked.
- Map collection stalled after 26 minutes on one run and I stopped it. Still unresolved.
- Two daily checklist items (fight in a hunting ground or adventure route, kill an enemy in battle) still need a real fight. Quick hunts are instant clears that do not count, and skipping battles with F2 does not count either. That module is not written yet.

## Optional LLM bits

`bd2_llm.py` is a thin client for any OpenAI-compatible endpoint with a 24h disk cache. It does two things: pick a branch option when OCR finds several, and write a short summary of collected dialogue. Without a key it falls back to clicking the first option and skips the summary. It never returns coordinates and cannot buy anything. The allowed action set is a closed list of four verbs.

`LLM决策点清单.md` lists the eight places a model would help and the ones I decided not to wire up.

## Files

```
bd2/                 capture, template matching, click and send
bd2_story.py         story loop
bd2_auto_daily.py    task orchestrator, currency guard, popup handling
bd2_guard.py         top-bar OCR and diff check
bd2_guest_story.py   guest cutscene walker
bd2_ledger.py        daily gains and spend report
bd2_llm.py           optional model client
bd2_launcher.py      tkinter GUI with checkboxes
templates/           cropped UI markers captured from my own client
```

## Disclaimer

Personal use only. Automating a live-service game probably violates its terms of service, and you are the one who gets the account flagged, not me. The templates are small UI crops from my own screen; no game assets are redistributed. The game, its art and its text belong to Neowiz.

中文说明见 [README.zh-CN.md](README.zh-CN.md).
