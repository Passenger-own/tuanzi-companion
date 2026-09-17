"""
桌面宠物提醒系统
- 久坐提醒：定时提醒用户起身活动
- 喝水提醒：定时提醒用户补充水分
- 健康提醒增强：总开关 / 自定义间隔持久化 / 专注模式静默队列 /
  环形进度条 / 每日打卡记录
"""

import os
import json
import time

from PyQt5.QtCore import QObject, QTimer, pyqtSignal, Qt, QPoint, QRectF
from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGraphicsDropShadowEffect, QApplication
)
from PyQt5.QtGui import QColor, QFont, QPainter, QPen

from config import (
    SIT_REMINDER_INTERVAL,
    WATER_REMINDER_INTERVAL,
    SIT_REMINDER_MSG,
    WATER_REMINDER_MSG,
    HEALTH_REMINDER_ENABLED,
    HEALTH_REMINDER_MIN_MINUTES,
    HEALTH_REMINDER_MAX_MINUTES,
    WATER_SNOOZE_DELAY_MS,
    SIT_SNOOZE_DELAY_MS,
    REMINDER_STATE_FILE,
    RING_PROGRESS_SIZE,
    RING_PROGRESS_COLOR,
    RING_PROGRESS_BG,
)

# 提醒类型对应的 emoji 图标
REMINDER_EMOJI = {
    "sit": "🐾",
    "water": "💧",
}

# 提醒类型对应的标题
REMINDER_TITLE = {
    "sit": "久坐提醒",
    "water": "喝水提醒",
}

# 稍后提醒的延迟时间（毫秒）—— 兼容旧引用，新逻辑按类型区分
SNOOZE_DELAY_MS = 10 * 60 * 1000  # 10 分钟


class ReminderDialog(QWidget):
    """半透明圆角提醒弹窗"""

    # 稍后提醒信号，参数为提醒类型
    snooze_requested = pyqtSignal(str)

    def __init__(self, reminder_type: str, message: str, parent=None):
        super().__init__(parent)
        self.reminder_type = reminder_type
        self.message = message

        self._init_window()
        self._init_ui()
        self._apply_style()

    def _init_window(self):
        """初始化无边框、置顶、圆角窗口"""
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(360, 200)

        # 默认居中显示
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

    def _init_ui(self):
        """构建弹窗内容"""
        emoji = REMINDER_EMOJI.get(self.reminder_type, "🔔")
        title = REMINDER_TITLE.get(self.reminder_type, "提醒")

        # 图标
        self.icon_label = QLabel(emoji)
        self.icon_label.setAlignment(Qt.AlignCenter)
        font_icon = QFont()
        font_icon.setPointSize(36)
        self.icon_label.setFont(font_icon)

        # 标题
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignCenter)
        font_title = QFont()
        font_title.setPointSize(12)
        font_title.setBold(True)
        self.title_label.setFont(font_title)

        # 消息
        self.message_label = QLabel(self.message)
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        font_msg = QFont()
        font_msg.setPointSize(10)
        self.message_label.setFont(font_msg)

        # 按钮：知道了
        self.ok_btn = QPushButton("知道了")
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        self.ok_btn.clicked.connect(self.close)

        # 按钮：稍后提醒
        self.snooze_btn = QPushButton("稍后提醒")
        self.snooze_btn.setCursor(Qt.PointingHandCursor)
        self.snooze_btn.clicked.connect(self._on_snooze)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.snooze_btn)

        # 主布局
        container = QWidget()
        container.setObjectName("dialogContainer")
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(8)
        main_layout.addWidget(self.icon_label)
        main_layout.addWidget(self.title_label)
        main_layout.addWidget(self.message_label)
        main_layout.addLayout(btn_layout)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

        # 阴影效果
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 4)
        container.setGraphicsEffect(shadow)

    def _apply_style(self):
        """应用 QSS 样式"""
        self.setStyleSheet("""
            QWidget#dialogContainer {
                background-color: rgba(255, 255, 255, 220);
                border-radius: 20px;
            }
            QLabel {
                color: #4A4A4A;
                background: transparent;
            }
            QPushButton {
                background-color: #FFE3EC;
                color: #D4637E;
                border: none;
                border-radius: 14px;
                padding: 8px 16px;
                font-size: 10pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #FFC9D9;
                color: #B84B66;
            }
            QPushButton:pressed {
                background-color: #FFB3C7;
            }
            QPushButton#ok_btn, QPushButton#snooze_btn {
                min-width: 80px;
            }
        """)

    def _on_snooze(self):
        """点击“稍后提醒”"""
        self.snooze_requested.emit(self.reminder_type)
        self.close()

    def mousePressEvent(self, event):
        """支持拖拽弹窗"""
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """拖拽中"""
        if hasattr(self, "_drag_pos") and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()


class HealthRingWidget(QWidget):
    """猫咪头顶环形进度条：自绘圆环，展示距离下次提醒剩余时长"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 无边框、置顶、透明背景、不抢焦点
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setFixedSize(RING_PROGRESS_SIZE, RING_PROGRESS_SIZE)

        self._progress = 0.0          # 0.0 ~ 1.0
        self._visible_type = None     # None / "water" / "sit"
        self._pet_window = None       # 跟随的猫咪窗口

        # 低频跟随定时器：避免侵入 pet_window，自行周期重定位
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(120)
        self._follow_timer.timeout.connect(self._reposition)

        self.hide()

    def set_progress(self, value: float):
        """设置进度（0.0~1.0）并刷新"""
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.0
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def set_visible_type(self, reminder_type):
        """设置当前显示的提醒类型；None 时隐藏"""
        self._visible_type = reminder_type
        if reminder_type is None:
            self.hide()
            self._follow_timer.stop()
        else:
            self.show()
            self.raise_()
            self._reposition()
            if not self._follow_timer.isActive() and self._pet_window is not None:
                self._follow_timer.start()

    def follow(self, pet_window):
        """跟随猫咪头部移动（放猫咪头顶左上）"""
        self._pet_window = pet_window
        self._reposition()
        if self._visible_type is not None and not self._follow_timer.isActive():
            self._follow_timer.start()

    def _reposition(self):
        """定位到猫咪头顶左上方"""
        if self._pet_window is None:
            return
        try:
            pet_pos = self._pet_window.pos()
            # 头顶左上：略微偏左，环形顶部贴近猫咪头部
            x = pet_pos.x() + 4
            y = pet_pos.y() - self.height() // 2
            self.move(x, y)
        except (RuntimeError, AttributeError):
            # pet_window 可能已被销毁
            pass

    def paintEvent(self, event):
        """绘制背景圆环 + 进度圆弧（无文字）"""
        if self._visible_type is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        size = min(self.width(), self.height())
        margin = 3
        rect = QRectF(
            (self.width() - size) / 2 + margin,
            (self.height() - size) / 2 + margin,
            size - 2 * margin,
            size - 2 * margin,
        )

        # 背景圆环
        bg = RING_PROGRESS_BG
        bg_pen = QPen(QColor(bg[0], bg[1], bg[2]), 3)
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(rect, 0, 360 * 16)

        # 进度圆弧（从 12 点方向开始，顺时针填充）
        color = RING_PROGRESS_COLOR
        prog_pen = QPen(QColor(color[0], color[1], color[2]), 3)
        prog_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(prog_pen)
        start_angle = 90 * 16                  # 12 点方向
        span = int(-self._progress * 360 * 16)  # 负值 = 顺时针
        if span != 0:
            painter.drawArc(rect, start_angle, span)


class ReminderSystem(QObject):
    """提醒系统：管理久坐和喝水两个定时器，支持总开关 / 持久化 / 专注静默 / 进度上报 / 打卡"""

    # 参数：提醒类型 ("sit"/"water")，提醒消息
    reminder_triggered = pyqtSignal(str, str)
    # (提醒类型, 进度 0.0~1.0)：驱动猫咪头顶环形进度条
    progress_updated = pyqtSignal(str, float)
    # 当前待执行的提醒队列 [(type, message), ...]：供主窗口柔性依次处理
    queue_updated = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 间隔（分钟）—— 优先从持久化恢复，否则用 config 默认值
        self._sit_minutes = SIT_REMINDER_INTERVAL
        self._water_minutes = WATER_REMINDER_INTERVAL
        # 总开关
        self._enabled = HEALTH_REMINDER_ENABLED
        # 专注模式静默标志
        self._focus_silenced = False
        # 专注期间积压的待释放提醒
        self._pending_queue = []
        # 每日打卡记录：{ "YYYY-MM-DD": count }
        self._water_log = {}
        self._sit_log = {}
        # 各提醒类型的上次触发/重置时间戳
        self._last_trigger = {"sit": time.time(), "water": time.time()}
        # 稍后提醒的临时单次定时器：type -> QTimer
        self._snooze_timers = {}

        # 久坐提醒定时器（分钟 -> 毫秒）
        self.sit_timer = QTimer(self)
        self.sit_timer.setInterval(self._sit_minutes * 60 * 1000)
        self.sit_timer.timeout.connect(self._on_sit_timeout)

        # 喝水提醒定时器（分钟 -> 毫秒）
        self.water_timer = QTimer(self)
        self.water_timer.setInterval(self._water_minutes * 60 * 1000)
        self.water_timer.timeout.connect(self._on_water_timeout)

        # 进度上报定时器（每秒触发一次）
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self._emit_progress)

        # 从持久化文件恢复状态（enabled / 间隔 / 打卡记录）
        self._load_state()

    # ============ 属性与开关 ============
    @property
    def enabled(self) -> bool:
        """总开关状态"""
        return self._enabled

    def set_enabled(self, value: bool):
        """总开关：关闭时停止所有定时器且不触发；开启时恢复"""
        self._enabled = bool(value)
        if self._enabled:
            # 开启：恢复定时器，重置触发时间戳，立即上报一次进度
            self.sit_timer.start()
            self.water_timer.start()
            self._progress_timer.start()
            self._last_trigger = {"sit": time.time(), "water": time.time()}
            self._emit_progress()
        else:
            # 关闭：停止所有定时器（含稍后提醒），进度归零
            self.sit_timer.stop()
            self.water_timer.stop()
            self._progress_timer.stop()
            for timer in self._snooze_timers.values():
                timer.stop()
            self._snooze_timers.clear()
            self.progress_updated.emit("water", 0.0)
            self.progress_updated.emit("sit", 0.0)
        self._save_state()

    def set_focus_silenced(self, value: bool):
        """专注模式静默：定时器继续倒计时，但触发的提醒进入队列而非立即 emit。
        专注模式退出（value=False）后依次释放队列。"""
        self._focus_silenced = bool(value)
        if not self._focus_silenced:
            self.release_pending()

    # ============ 生命周期 ============
    def start(self):
        """启动定时器（受总开关控制）"""
        if not self._enabled:
            return
        self.sit_timer.start()
        self.water_timer.start()
        self._progress_timer.start()
        # 启动时重置进度起点，环形从 0 开始增长
        self._last_trigger = {"sit": time.time(), "water": time.time()}
        self._emit_progress()

    def stop(self):
        """停止所有定时器"""
        self.sit_timer.stop()
        self.water_timer.stop()
        self._progress_timer.stop()
        for timer in self._snooze_timers.values():
            timer.stop()
        self._snooze_timers.clear()

    # ============ 间隔 ============
    def update_intervals(self, sit_minutes: int, water_minutes: int):
        """更新提醒间隔并重启定时器，额外持久化到文件"""
        sit_minutes = self._clamp_minutes(sit_minutes)
        water_minutes = self._clamp_minutes(water_minutes)
        self._sit_minutes = sit_minutes
        self._water_minutes = water_minutes
        self.sit_timer.setInterval(sit_minutes * 60 * 1000)
        self.water_timer.setInterval(water_minutes * 60 * 1000)
        if self._enabled:
            self.sit_timer.start()
            self.water_timer.start()
            self._progress_timer.start()
        self._save_state()

    @staticmethod
    def _clamp_minutes(value):
        """将间隔限制在配置允许的范围内"""
        try:
            value = int(value)
        except (TypeError, ValueError):
            return SIT_REMINDER_INTERVAL
        if value < HEALTH_REMINDER_MIN_MINUTES:
            return HEALTH_REMINDER_MIN_MINUTES
        if value > HEALTH_REMINDER_MAX_MINUTES:
            return HEALTH_REMINDER_MAX_MINUTES
        return value

    # ============ 触发与队列 ============
    def _on_sit_timeout(self):
        """触发久坐提醒"""
        self._trigger("sit", SIT_REMINDER_MSG)

    def _on_water_timeout(self):
        """触发喝水提醒"""
        self._trigger("water", WATER_REMINDER_MSG)

    def _trigger(self, reminder_type: str, message: str):
        """统一触发逻辑：更新进度起点，再根据开关/专注状态决定立即 emit 或入队"""
        # 重置进度起点（下一轮倒计时从这里开始）
        self._last_trigger[reminder_type] = time.time()
        if not self._enabled:
            return
        if self._focus_silenced:
            # 专注期间入队，不立即打扰
            self._pending_queue.append((reminder_type, message))
            self.queue_updated.emit(list(self._pending_queue))
        else:
            self.reminder_triggered.emit(reminder_type, message)

    def release_pending(self):
        """专注退出后调用：依次 emit 队列中的提醒，清空队列"""
        if not self._pending_queue:
            return
        pending = list(self._pending_queue)
        self._pending_queue.clear()
        self.queue_updated.emit([])
        for reminder_type, message in pending:
            self.reminder_triggered.emit(reminder_type, message)

    # ============ 稍后提醒 ============
    def snooze(self, reminder_type: str, message: str):
        """安排稍后提醒（按类型区分延迟：water/sit）"""
        delay = WATER_SNOOZE_DELAY_MS if reminder_type == "water" else SIT_SNOOZE_DELAY_MS
        # 复用同一个类型的稍后定时器
        if reminder_type in self._snooze_timers:
            self._snooze_timers[reminder_type].stop()

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(delay)
        timer.timeout.connect(lambda: self._on_snooze_timeout(reminder_type, message, timer))
        self._snooze_timers[reminder_type] = timer
        timer.start()

    def _on_snooze_timeout(self, reminder_type: str, message: str, timer: QTimer):
        """稍后提醒到期"""
        self._last_trigger[reminder_type] = time.time()
        if self._snooze_timers.get(reminder_type) is timer:
            self._snooze_timers.pop(reminder_type, None)
        if not self._enabled:
            return
        if self._focus_silenced:
            self._pending_queue.append((reminder_type, message))
            self.queue_updated.emit(list(self._pending_queue))
        else:
            self.reminder_triggered.emit(reminder_type, message)

    # ============ 进度上报 ============
    def _emit_progress(self):
        """每秒计算并上报各提醒类型的剩余进度（0.0~1.0）。
        总开关关闭时不 emit。"""
        if not self._enabled:
            return
        now = time.time()
        for rtype, minutes in (("sit", self._sit_minutes), ("water", self._water_minutes)):
            interval_sec = minutes * 60
            if interval_sec <= 0:
                progress = 0.0
            else:
                elapsed = now - self._last_trigger.get(rtype, now)
                progress = max(0.0, min(1.0, elapsed / interval_sec))
            self.progress_updated.emit(rtype, progress)

    # ============ 打卡记录 ============
    def log_checkin(self, reminder_type: str):
        """记录今日打卡次数到持久化文件，并重置对应倒计时"""
        today = time.strftime("%Y-%m-%d")
        log = self._water_log if reminder_type == "water" else self._sit_log
        log[today] = log.get(today, 0) + 1
        # 取消该类型可能存在的稍后提醒
        if reminder_type in self._snooze_timers:
            self._snooze_timers[reminder_type].stop()
            self._snooze_timers.pop(reminder_type, None)
        # 重置倒计时起点并重启对应定时器
        self._last_trigger[reminder_type] = time.time()
        if self._enabled:
            if reminder_type == "water":
                self.water_timer.start()
            else:
                self.sit_timer.start()
            self._emit_progress()
        self._save_state()

    def get_water_count_today(self) -> int:
        """返回今日喝水打卡次数"""
        today = time.strftime("%Y-%m-%d")
        return self._water_log.get(today, 0)

    def get_sit_count_today(self) -> int:
        """返回今日久坐活动打卡次数"""
        today = time.strftime("%Y-%m-%d")
        return self._sit_log.get(today, 0)

    # ============ 状态查询 ============
    def get_state(self) -> dict:
        """返回当前配置 dict（供设置面板初始化）"""
        return {
            "enabled": self._enabled,
            "sit_minutes": self._sit_minutes,
            "water_minutes": self._water_minutes,
            "water_count_today": self.get_water_count_today(),
            "sit_count_today": self.get_sit_count_today(),
            "focus_silenced": self._focus_silenced,
            "pending_count": len(self._pending_queue),
        }

    # ============ 持久化 ============
    def _load_state(self):
        """从 REMINDER_STATE_FILE 恢复 {enabled, sit_minutes, water_minutes, water_log, sit_log}"""
        try:
            if not os.path.exists(REMINDER_STATE_FILE):
                return
            with open(REMINDER_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            if "enabled" in data:
                self._enabled = bool(data["enabled"])
            if "sit_minutes" in data:
                self._sit_minutes = self._clamp_minutes(data["sit_minutes"])
            if "water_minutes" in data:
                self._water_minutes = self._clamp_minutes(data["water_minutes"])
            if isinstance(data.get("water_log"), dict):
                self._water_log = data["water_log"]
            if isinstance(data.get("sit_log"), dict):
                self._sit_log = data["sit_log"]
            # 同步定时器间隔到恢复值
            self.sit_timer.setInterval(self._sit_minutes * 60 * 1000)
            self.water_timer.setInterval(self._water_minutes * 60 * 1000)
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            # 文件损坏或不可读时静默回退到默认配置
            pass

    def _save_state(self):
        """保存状态到 REMINDER_STATE_FILE"""
        try:
            directory = os.path.dirname(REMINDER_STATE_FILE)
            if directory:
                os.makedirs(directory, exist_ok=True)
            data = {
                "enabled": self._enabled,
                "sit_minutes": self._sit_minutes,
                "water_minutes": self._water_minutes,
                "water_log": self._water_log,
                "sit_log": self._sit_log,
            }
            with open(REMINDER_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except (OSError, ValueError, TypeError):
            # 写入失败不影响运行
            pass


if __name__ == "__main__":
    # 简单自测：弹出提醒 + 验证新增接口（环形进度 / 队列 / 打卡 / 状态）
    import sys
    app = QApplication(sys.argv)

    def on_triggered(rtype: str, msg: str):
        dialog = ReminderDialog(rtype, msg)
        dialog.snooze_requested.connect(
            lambda t: print(f"[{t}] 已设置稍后提醒")
        )
        dialog.show()

    system = ReminderSystem()
    system.reminder_triggered.connect(on_triggered)
    system.queue_updated.connect(lambda q: print(f"[队列] 待处理提醒: {q}"))
    system.start()

    # 验证新增接口
    print("初始状态:", system.get_state())
    print("今日喝水打卡:", system.get_water_count_today())
    print("今日久坐打卡:", system.get_sit_count_today())

    # 演示环形进度条：跟随久坐进度
    ring = HealthRingWidget()

    def on_progress(rtype, progress):
        if rtype == "sit":
            ring.set_progress(progress)

    system.progress_updated.connect(on_progress)
    ring.set_visible_type("sit")

    # 立即触发一次久坐提醒用于演示
    QTimer.singleShot(500, lambda: system.reminder_triggered.emit("sit", SIT_REMINDER_MSG))

    sys.exit(app.exec_())
