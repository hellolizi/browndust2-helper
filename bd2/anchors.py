"""锚点定义：优先级、提示文案、点击与等待参数。"""

# 优先级从高到低：先处理弹窗/结算，再处理对话和关卡推进，最后才是地图导航
ORDER = ["result", "popup", "skip", "next", "battle", "quest", "menu", "recover"]

ANCHORS = {
    "result": {
        "label": "战斗结算",
        "prompt": "把鼠标移到【战斗胜利后结算界面】的『确认 / 继续』按钮中心",
        "click": True,
        "wait": 1.2,
        "thr": 0.85,
    },
    "popup": {
        "label": "通用弹窗",
        "prompt": "把鼠标移到【获得奖励 / 升级 / 提示弹窗】的『确认』按钮中心",
        "click": True,
        "wait": 1.0,
        "thr": 0.85,
    },
    "skip": {
        "label": "对话快进",
        "prompt": "把鼠标移到【剧情对话界面】的『跳过 / 快进』按钮中心",
        "click": True,
        "wait": 0.6,
        "thr": 0.85,
    },
    "next": {
        "label": "下一关",
        "prompt": "把鼠标移到【关卡完成后】的『下一关 / 再次挑战 / 继续』按钮中心",
        "click": True,
        "wait": 1.4,
        "thr": 0.85,
    },
    "battle": {
        "label": "战斗中标志",
        "prompt": "把鼠标移到【只在战斗界面出现】的元素上（例如右下角『自动战斗』按钮），这里只识别不点击",
        "click": False,
        "wait": 0.8,
        "thr": 0.85,
    },
    "quest": {
        "label": "主线任务追踪",
        "prompt": "回到地图界面，把鼠标移到右侧的『主线任务追踪条』上（点它会自动寻路）",
        "click": True,
        "wait": 2.0,
        "thr": 0.85,
    },
    "menu": {
        "label": "关卡选择",
        "prompt": "（可选）把鼠标移到卡带/章节界面的『进入 / 开始战斗』按钮；没有就直接跳过",
        "click": True,
        "wait": 1.5,
        "thr": 0.85,
    },
    "recover": {
        "label": "异常恢复",
        "prompt": "（可选）把鼠标移到能『返回主页 / 关闭弹窗』的按钮；没有就直接跳过",
        "click": True,
        "wait": 1.2,
        "thr": 0.85,
    },
}

# 校准时的提问顺序：按实际推图流程走，用户更容易理解
CALIB_ORDER = ["quest", "battle", "skip", "result", "next", "popup", "menu", "recover"]
