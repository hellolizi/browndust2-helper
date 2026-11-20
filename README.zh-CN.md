# 棕色尘埃2 自动推剧情助手（PC 客户端）

纯 Python + numpy 的轻量自动化：**截屏 → 模板匹配 → 点击**，不注入游戏、不改内存、不读包。
在真实客户端（v2.38.11，1920×1080 全屏）上验证可连续推进剧情对话、处理“跳过对话”确认框、选择对话分支。

---

## 1. 为什么自研（GitHub 调研结论）

| 项目 | 星标 | 能力 | 是否推剧情 |
|---|---|---|---|
| [MFABD2](https://github.com/sunyink/MFABD2) | 665 | 日常/周常/活动/跑商/采集，MaaFramework 管线 | 否（Issue #233 仍 open：「能不能加个卡带困难极难自动前进脚本」） |
| YES-BD2 | 186 | 日常收菜 | 否 |
| Maa-Assistant-Browndust2 | — | 日常助手 | 否 |
| ok-bd2 | — | 跑商/日常 | 否 |
| [autogoBD2](https://github.com/FlawlessEmpyreal/autogoBD2) | 3 | C++ + YOLO，仅 1–2 章撞怪，2026-06 停更、无 Release | 部分 |

结论：**没有成熟的“自动推剧情”方案**。MFABD2 的 `Collect_Navigation` 是卡带内“采集导航”，不是剧情推进；它的 `Collect_Launcher` 里有 `label: 剧情` 的卡带分类，但用途是采集资源。

因此按“最小依赖”自研：屏幕固定 ROI + 1–2 FPS + 纯 numpy NCC，无 GPU、无训练、无模型。

## 2. 实现要点（与 GitHub 参考的对应）

- **坐标体系**：MFABD2 明确写“坐标 1280×720 由 1920 实测点按 ×2/3 换算”，本机 1080p 直接按 ×1.5 反推，所有 ROI 用 1080p 绝对坐标。
- **对话推进**：MFABD2 `AutoBattle_Egress_TurnBack_SkipTalk` 用模板 `Chaga_ProductNext.png`（ROI `[796,2,455,93]`，720p）判定“场景转场/跳过对话”。本脚本改用更稳的**右上角 F2 跳过图标**作为“处于剧情中”的判据（跨场景匹配稳定在 0.90–1.00）。
- **跳过确认框**：游戏内 F2 会弹「跳过对话 / 取消 / 确认 / 播放下一个」，本脚本用标题模板命中后点“确认”（固定点 `(975,790)`；键盘提示为 `Enter or Space`）。
- **分支选项**：三行布局（行中心 y≈820/905/991，前两行灰显不可用）与两行布局都遇到过。用 `cycle` 在“中心点”与三个候选行之间轮转：灰显行点了没反应，碰到第一个可用行即被选中。
- **黑屏转场**：“查看下一个”按钮只在整屏极暗时出现。改为**画面平均亮度 < 14 就点 `(1605,945)`**（`config.json` 的 `dark` 段），不再用模板匹配——纯黑模板会误匹配加载画面。
- **转场等待**：识别不到任何锚点时**不点击**，只等待；`watchdog.none_stop=90s` 兜底退出。

## 3. 目录

```
bd2/                # 基础库
  win32.py          # 窗口查找/DPI/客户区/BitBlt 抓图/SendInput 点击/热键
  vision.py         # 灰度 + 4x 降采样粗搜 + 1/2 尺度精修 NCC（纯 numpy）
  imgio.py          # BMP 读写 + 自写 PNG 编码（零依赖）
bd2_story.py        # 主循环（配置驱动）
bd2_team.py         # 自动编队 / 战败换阵容重试 / 升级（半自动，需一次性标定）
config.json         # 锚点配置
team_config.json    # 编队坐标配置（calibrate 生成）
templates/          # 已采集模板
shot.py             # 截图（支持 --crop/--scale）
zoom.py             # 局部放大截图（辨认小图标）
mktpl.py            # 从实时画面裁一块存 BMP 模板
probe.py            # 在实时画面测试某模板的匹配分
click.py / key.py   # 单次点击 / 发送按键
bench.py            # 1080p 性能基准
selftest.py         # 自检（BMP 往返、匹配正确性、窗口枚举）
calibrate.py        # 旧版交互校准（可选，现多用 mktpl）
fake_game.py / e2e_test.py / e2e_config.json  # 无游戏时的假窗口端到端测试
```

## 4. 使用

```powershell
pip install numpy
python selftest.py                     # 环境自检
python bd2_story.py --dry-run --verbose --max-seconds 10   # 只识别不点击
python bd2_story.py                    # 正式运行；F8 暂停/继续，F10 停止
```

要求：游戏窗口标题 `BrownDust II`、类名 `UnityWndClass`、客户区 1920×1080；脚本运行前先手动进入**任意剧情关卡**。

## 5. config.json 结构

```json
{
  "client": [1920, 1080],
  "fps": 2.0,
  "anchors": [
    {
      "name": "skipconfirm",
      "tpl": "templates/skip_title.bmp",   // 模板（BMP）
      "roi": [700, 220, 600, 140],         // 屏幕绝对 ROI(1080p)
      "thr": 0.8,                          // NCC 阈值
      "action": {"type": "click", "pos": [975, 790]},
      "wait": 1.8, "cooldown": 3.0
    },
    {
      "name": "story",
      "tpl": "templates/story_f2.bmp",
      "roi": [1500, 10, 400, 120],
      "thr": 0.9,
      "action": {"type": "cycle", "positions": [[960, 626], [960, 905]]},
      "wait": 2.2, "cooldown": 2.2
    }
  ]
}
```

- `anchors` 顺序即优先级，命中第一个就执行。
- `action.type`：`click`（`pos` 固定点 / `center` / `match`+`offset`）、`cycle`（轮流点击多个点）、`none`。

## 6. 已验证 / 未覆盖

已验证（真实客户端）：
- 连续 4 分钟自动推进（日志 `story` 分数 0.90–1.00，跨场景稳定）。
- 通过“跳过对话”确认框（`skipconfirm` 优先命中并点确认）。
- 通过至少两处剧情分支选择（宽行、紧凑行各一次）。
- 转场黑屏期间不误点。

未覆盖（需按第 7 节补模板）：
- **战斗**：自动战斗按钮、战斗结算“确认/继续”。当前若进入战斗会因识别不到锚点而停在等待，直到 `none_stop` 退出。
- **编队界面**：本账号剧情卡带基本都是 100%，重播只走对话不出战斗；活动/狩猎模式进去是野外探索，暂未在真机上抓到带“编辑队伍”的战斗准备界面。因此 `bd2_team.py` 的首版是按“可标定”设计交付的（见第 10 节），坐标需在真实战斗准备界面出现时标定一次。

## 7. 自动编队 / 换阵容 / 升级（`bd2_team.py`）

界面没固定前不硬编码坐标，全部交给一次性标定：

```powershell
python bd2_team.py calibrate
# 按提示把鼠标停在：编辑队伍按钮 / 确定按钮 / 开始战斗按钮 / 第1个槽位 / 角色列表第1个头像
# 每次停好按回车记录；槽位与角色网格按 --slot-step / --roster-cols / --roster-dx / --roster-dy 自动铺开

python bd2_team.py build --variant 0     # 按第 0 套阵容配队并开战
python bd2_team.py retry --max 4         # 战败检测 → 返回 → 换下一套阵容 → 再开战
python bd2_team.py levelup --times 3     # 给当前角色点 3 次升级（有次数上限，不吃光材料）
```

- `team_config.json` 的 `teams` 是“每套阵容各选角色列表第几个”的索引表，例如 `[[0,1,2,3,4],[5,6,7,8,9]]`：战败一次换下一套。
- `retry` 依赖 `templates/defeat.bmp`：首次战败结算时用 `python mktpl.py --rect "x,y,w,h" --out templates/defeat.bmp` 采一张（只裁“失败/战败”字样，别带会动的数值）。
- 升级只按固定次数点，不做“升到满级”——升级消耗金币/材料，必须有上限。

## 7. 扩展方法（以战斗为例）

1. 手动进入战斗，等结算界面出现。
2. `python shot.py --out debug/battle.png` 存图，找出按钮位置。
3. `python mktpl.py --rect "x,y,w,h" --out templates/result.bmp`（只裁按钮，不要带会动的数字/动画）。
4. `python probe.py --tpl templates/result.bmp --roi "x,y,w,h"` 确认分数 > 0.95，再切场景复测。
5. 在 `config.json` 的 `anchors` **最前面**加：
   ```json
   {"name":"result","tpl":"templates/result.bmp","roi":[...],"thr":0.9,
    "action":{"type":"click","pos":[x,y]},"wait":2.0,"cooldown":3.0}
   ```

## 8. 性能

1080p 实测（bench.py）：截图 ~21 ms/帧，6 个 64×64 锚点识别 ~27 ms，单帧约 48 ms；2 FPS 下单核占用 <10%。

## 9. 边界

- 只做“截屏 + 鼠标点击”，不修改游戏文件、不读写内存、不联网。
- 点击前会把游戏窗口切到前台；若切不到会直接停止，避免误点其他窗口。
- 游戏更新可能改变 UI 布局/按钮，届时用 `mktpl.py` 重采模板即可。

## 10. BepInEx / BDX 状态

- 游戏根目录 `D:\Neowiz\Browndust2\BrownDust2_10000002`，Unity 2022.3.62f2（Mono）。
- 已安装 **BepInEx 5.4.23.6**（win x64 官方 Release），7 个插件全部加载，Chainloader startup complete。
- 旧版 5.4.22 备份目录已删除（按你的要求）。
- **BDX（BrownDustX）2.36.7.1 对本作 v2.38.11 不适配**，游戏内弹窗明示“尚未适配”并自动停用；GitHub 无 BDX 官方 Release（只在作者 Discord 分发），暂无新版可装。
- 本脚本与 BepInEx 无关：不装插件也能跑；插件只影响游戏内表现。
