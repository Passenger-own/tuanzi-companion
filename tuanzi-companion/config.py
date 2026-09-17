"""
桌面宠物配置文件 v7.0.0
完整实现：视频渲染重构、专注模式退出规则、全动作过渡优化、窗口置顶

获取 DeepSeek API Key: https://platform.deepseek.com/
"""
import os

# ============ DeepSeek API 配置 ============
# 优先从环境变量读取（推荐），也可直接在下方填写
# 开源发布时请保持此处为空，通过环境变量 DEEPSEEK_API_KEY 注入
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# ============ 提醒设置 ============
SIT_REMINDER_INTERVAL = 60
WATER_REMINDER_INTERVAL = 45
SIT_REMINDER_MSG = "坐了很久啦，起来活动活动吧～"
WATER_REMINDER_MSG = "该喝水了，保持水分摄入很重要哦～"

# ============ 宠物设置 ============
PET_NAME = "团子"
PET_SIZE = 150
ANIMATION_INTERVAL = 3000

# ============ 动画触发时间配置 ============
IDLE_TIMEOUT = 30000
SLEEP_TIMEOUT = 300000
LIE_SIDE_CHAT_TIMEOUT = 600000
LIE_BACK_CLICK_COUNT = 3
LIE_BACK_CLICK_WINDOW = 800  # 800ms滚动窗口内连续三击触发撒娇

# ============ 动作冷却配置 ============
ACTION_COOLDOWN = {
    "lie_back": 6000,
    "eat": 0,
    "stretch": 0,
    "happy": 0,
    "idle": 0,
    "lie_side": 0,
    "sleep": 0,
}

# ============ 动画优先级 ============
ACTION_PRIORITY = {
    "idle": 1,
    "lie_side": 2,
    "lie_back": 2,
    "happy": 3,
    "eat": 3,
    "stretch": 3,
    "sleep": 4,
}

# ============ 互斥规则 ============
SLEEP_BLOCKED_ACTIONS = {"happy", "eat", "stretch", "lie_back", "lie_side"}

# ============ 场景限定动作 ============
SCENE_LIMITED_ACTIONS = {"eat", "stretch", "sleep", "lie_side"}
GENERAL_ACTIONS = {"idle", "lie_back", "happy"}
IDLE_ROTATION_TIMEOUT = 60000
IDLE_ROTATION_ACTIONS = []

# ============ lie_back 撒娇 ============
LIE_BACK_LOOP_COUNT = 2

# ============ 状态自动降级 ============
SLEEP_AUTO_DOWNGRADE_TIMEOUT = 600000
LIE_SIDE_AUTO_DOWNGRADE_TIMEOUT = 900000

# ============ 事件排队机制 ============
EVENT_QUEUE_ENABLED = True

# ============ 气泡交互配置 ============
BUBBLE_ENABLED = True
BUBBLE_DURATION_MS = 3500
BUBBLE_BG_COLOR = (255, 228, 235, 210)      # 浅粉半透明
BUBBLE_TEXT_COLOR = (110, 110, 110)          # 浅灰软圆字体
BUBBLE_ROUNDED_RADIUS = 14
BUBBLE_SHOW_DELAY_MS = 500                   # 动作播放 0.5s 后弹出气泡

# ============ 专注模式退出专属气泡 ============
FOCUS_EXIT_BUBBLE_TEXT = "我睡醒啦！ฅ՞・ᴥ・՞ฅ~"
FOCUS_EXIT_BUBBLE_DELAY_MS = 500  # 伸懒腰播放0.5s后弹出
FOCUS_EXIT_ANIMATION = "stretch"

# 每个动作配套气泡文案（随机切换）
ACTION_BUBBLE_TEXTS = {
    "idle": [
        "乖乖陪你办公中 (๑・̀ㅂ・́)و✧~",
        "安安静静蹲旁边，不打扰你哦ฅ˙Ⱉ˙ฅ",
        "今天天气真好呀～要不要摸摸我？",
        "主人在忙什么呢？需要休息一下吗？",
        "我在这里哦～(=^･ω･^=)",
        "发呆中...思考猫生哲学～",
        "伸个懒腰～主人要不要也活动一下？",
        "看到你就很开心～(๑•̀ㅂ•́)و✧",
    ],
    "lie_back": [
        "软软躺平贴贴你～ฅ՞・ﻌ・՞ฅ~",
        "被你摸舒服啦～蜷成小棉花꒰ঌ˶・༝・˶໒꒱",
    ],
    "lie_side": [
        "瘫成一团小毛球，懒懒放空中～૮₍˶・ᴗ・˶₎ა",
        "晒晒太阳躺平，万事不用急ฅ՞・ﻌ・՞ฅ",
    ],
    "sleep": [
        "呼呼 zzz… 浅浅睡一会，等你叫我～",
        "眼皮沉沉，先打个小盹ฅ˙Ⱉ˙ฅ",
    ],
    "happy": [
        "看到你超开心！挥爪打招呼૮₍˶・༝・˶₎ა",
        "今天也要元气满满喵～ฅ՞・ᴥ・՞ฅ",
    ],
    "eat": [
        "咕嘟咕嘟喝水水🥛~ 你也该喝水啦～",
        "喝水变水润小猫ฅ˙Ⱉ˙ฅ你变成水润小人了吗～",
    ],
    "stretch": [
        "伸个懒腰充充电～",
    ],
}

# ============ 数据存储 ============
# 检测是否在 .app 包内运行：如果是，数据目录放到 ~/Library/Application Support（可写）
# 否则使用项目目录下的 data/（开发模式）
_APP_MODE = os.path.dirname(os.path.abspath(__file__)).endswith("Resources") or \
            ".app/Contents/Resources" in os.path.dirname(os.path.abspath(__file__))

if _APP_MODE:
    _SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/桌面宠物")
    DATA_DIR = os.path.join(_SUPPORT_DIR, "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

os.makedirs(DATA_DIR, exist_ok=True)
TODO_FILE = os.path.join(DATA_DIR, "todo.json")
NOTES_FILE = os.path.join(DATA_DIR, "notes.json")
CONFIG_FILE = os.path.join(DATA_DIR, "pet_config.json")
CHAT_HISTORY_FILE = os.path.join(DATA_DIR, "chat_history.json")
# 健康提醒状态持久化（总开关 / 自定义间隔 / 每日打卡记录），重启不丢失
REMINDER_STATE_FILE = os.path.join(DATA_DIR, "reminder_state.json")

# ============ 视频动画设置 ============
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
VIDEO_DIR = os.path.join(ASSETS_DIR, "video")

VIDEO_EXTENSIONS = [".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v", ".gif"]

# 绿幕抠像
CHROMA_KEY_ENABLED = True
CHROMA_KEY_COLOR = (0, 255, 0)
CHROMA_KEY_THRESHOLD = 100

# 动作名称 → 视频文件名关键词映射
VIDEO_MAPPING = {
    "idle": "idle",
    "lie_back": "lie_back",
    "lie_side": "lie_side",
    "sleep": "sleep",
    "happy": "happy",
    "eat": "eat",
    "stretch": "stretch",
}

VIDEO_ALIASES = {
    "idle": ["待机", "idle", "sit", "default"],
    "lie_back": ["躺平", "露肚皮", "lie_back", "back", "belly"],
    "lie_side": ["侧躺", "lie_side", "side"],
    "sleep": ["睡觉", "睡眠", "sleep", "sleeping"],
    "happy": ["开心", "蹦跳", "happy", "joy", "play"],
    "eat": ["进食", "喝水", "eat", "drink", "eating"],
    "stretch": ["伸懒腰", "蹭屏幕", "stretch", "yawn"],
}

# 视频重试机制
VIDEO_LOAD_RETRY_COUNT = 3
VIDEO_LOAD_RETRY_DELAY_MS = 200  # 重试间隔

# ============ 全动作过渡配置 ============
# 过渡模式下的淡入淡出时长（毫秒）
TRANSITION_FADE_IN_MS = 150   # 画面淡入
TRANSITION_FADE_OUT_MS = 150  # 画面淡出

# 分类差异化过渡时长
TRANSITION_SHORT_MS = 200      # 短时微动作（eat）
TRANSITION_LONG_MS = 400       # 长交互动作（stretch/lie_back/sleep）
TRANSITION_FOCUS_EXIT_MS = 600  # 专注模式退出专属过渡（stretch→idle 丝滑衔接）

# 需要独立缓存的高频动作
HIGH_FREQUENCY_ACTIONS = {"idle", "stretch"}

# 预加载缓存数量
PRELOAD_CACHE_SIZE = 5

# ============ 窗口置顶配置 ============
WINDOW_TOP_HINT = True          # 窗口永久置顶
WINDOW_INTERACT_THROUGH = False  # 交互穿透（点击穿透到桌面）
WINDOW_RESTART_PERSIST = True   # 重启后恢复置顶

# 支持的视频文件扩展名（支持macOS CoreMedia格式）
SUPPORTED_VIDEO_EXTENSIONS = [".mp4", ".mov"]

# ============ 事件 → 触发动作映射 ============
EVENT_ACTION_MAP = {
    "on_launch": "idle",
    "on_hover": "happy",
    "on_drag": "happy",
    "on_click": "idle",
    "on_multi_click": "lie_back",
    "on_chat_open": "idle",
    "on_chat_end": "happy",
    "on_reminder_sit": "stretch",
    "on_reminder_water": "eat",
    "on_water_log": "eat",
    "on_rest_log": "happy",
    "on_intimacy_up": "happy",
    "on_idle_short": "idle",
    "on_idle_long": "sleep",
    "on_no_chat_long": "lie_side",
    "on_focus_mode": "lie_side",
    "on_dnd_mode": "sleep",
}

# ============ 亲密度系统 ============
INTIMACY_ENABLED = True

# ============ 健康提醒增强配置 ============
# 总开关默认值（运行时从 reminder_state.json 恢复）
HEALTH_REMINDER_ENABLED = True
# 自定义间隔范围（分钟）
HEALTH_REMINDER_MIN_MINUTES = 1
HEALTH_REMINDER_MAX_MINUTES = 90
# 稍后提醒延迟（毫秒）：喝水延后 10 分钟，久坐延后 15 分钟
WATER_SNOOZE_DELAY_MS = 10 * 60 * 1000
SIT_SNOOZE_DELAY_MS = 15 * 60 * 1000
# 提醒触发时的随机气泡文案（不粗暴打断当前动画，平滑过渡）
WATER_REMINDER_BUBBLES = [
    "咕嘟咕嘟补水啦💧~ฅ՞•ﻌ•՞ฅ",
    "该喝口水润润嗓子哦",
]
SIT_REMINDER_BUBBLES = [
    "坐太久啦，起来活动一下૮₍˶•ᴗ•˶₎ა",
    "伸伸胳膊放松腰背哦～",
]
# 打卡完成后的反馈气泡
WATER_DONE_BUBBLE = "真棒！多喝水皮肤好好～"
SIT_DONE_BUBBLE = "活动完更有精神啦！"
# 计算器完成反馈气泡
CALC_DONE_BUBBLE = "算好啦～ฅ˙Ⱉ˙ฅ"

# 工具面板打开时的气泡文案（每个功能不同）
TOOL_PANEL_BUBBLES = {
    "todo": "一起看看今天要做些什么吧～📋",
    "calc": "需要算什么？我来帮你～🧮",
    "notes": "随手记下重要的事情吧～📝",
    "shortcuts": "常用快捷键都在这里啦～⌨️",
    "reminder_settings": "来调整喝水和久坐提醒吧～⏰",
}

# ============ 毛玻璃举牌弹窗统一样式 ============
# 低饱和马卡龙毛玻璃，28px 大圆角，柔和浅粉/奶蓝半透底色
GLASS_FADE_MS = 150              # 统一 0.15s 淡入淡出
GLASS_RADIUS = 28                # 大圆角
GLASS_PINK_BG = "rgba(255, 228, 235, 200)"   # 浅粉半透明
GLASS_BLUE_BG = "rgba(220, 232, 245, 200)"   # 奶蓝半透明
GLASS_TEXT_COLOR = "#6E6E6E"     # 浅灰软圆字体
GLASS_FONT_FAMILY = "PingFang SC, Microsoft YaHei"
# 弹簧弹出缓动动画时长
GLASS_SPRING_MS = 260
# 环形进度条（猫咪头顶常驻，展示距离下次提醒剩余时长）
RING_PROGRESS_SIZE = 26
RING_PROGRESS_COLOR = (255, 182, 193)   # 浅粉
RING_PROGRESS_BG = (230, 230, 230)      # 浅灰底
