"""
桌面宠物主窗口 v7.0.0
完整实现：
1. 素材路径智能校验（模糊匹配、弹窗提示）
2. 视频渲染架构重构（独立缓存、重试机制、帧管理）
3. 专注模式退出专属交互（stretch强制、专属气泡、跟随）
4. 全动作过渡优化（淡入淡出、差异化时长、预加载）
5. 窗口置顶与交互穿透

使用 QMediaPlayer + QAbstractVideoSurface 实现透明视频播放
"""
import os
import sys
import json
import random
import logging

from PyQt5.QtWidgets import (
    QWidget, QLabel, QMenu, QAction, QApplication,
    QMessageBox, QVBoxLayout, QHBoxLayout, QSizePolicy, QDialog, QDialogButtonBox,
    QLabel as QLabel2, QPushButton, QInputDialog, QLineEdit
)
from PyQt5.QtCore import Qt, QTimer, QPoint, QSize, QUrl, pyqtSignal, QPointF, QRectF, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QPixmap, QPainter, QFont, QColor, QIcon, QImage, QFontMetrics, QPolygonF, QMovie

try:
    from PyQt5.QtOpenGL import QGLWidget
    HAS_OPENGL = True
except ImportError:
    HAS_OPENGL = False

from PyQt5.QtMultimedia import (
    QMediaPlayer, QMediaContent, QAbstractVideoSurface,
    QVideoFrame, QVideoSurfaceFormat, QMediaPlaylist
)

import config
from ai_chat import ChatWindow
from reminder import ReminderSystem, ReminderDialog, HealthRingWidget
from tools_panel import ToolsPanel
from glass_widgets import (
    TodoGlassDialog, CalculatorGlassDialog, NotesGlassDialog,
    ShortcutGlassDialog, ReminderSettingGlassDialog, ReminderActionGlassDialog,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 需要循环播放的动作（lie_back 由 StoppedState 计数循环，不放入此集合）
LOOP_ACTIONS = {"idle", "sleep", "lie_side"}

# 动作替代映射
FALLBACK_ACTIONS = {
    "idle": ["idle", "lie_side", "lie_back", "sleep"],
    "lie_back": ["lie_back", "idle", "lie_side"],
    "lie_side": ["lie_side", "idle", "lie_back"],
    "sleep": ["sleep", "idle", "lie_side"],
    "happy": ["happy", "idle"],
    "eat": ["eat", "idle", "happy"],
    "stretch": ["stretch", "idle", "happy"],
}

# 短动画（播放一次后自动回idle）
SHORT_ACTIONS = {"eat", "happy"}

# 长动画（播放一次后回idle或维持当前状态）
LONG_ACTIONS = {"stretch"}


class VideoManager:
    """视频管理器：智能路径匹配、缓存管理、加载重试"""

    def __init__(self):
        self._video_paths = {}
        self._media_cache = {}
        self._missing_actions = []
        self._load_errors = set()

    def scan_videos(self, video_dir):
        """全量扫描视频目录，智能匹配动作"""
        self._video_paths = {}
        self._missing_actions = []

        if not os.path.isdir(video_dir):
            logger.warning(f"视频目录不存在: {video_dir}")
            return self._video_paths

        # 收集所有可用视频文件（小写化文件名）
        available_files = {}
        try:
            for f in os.listdir(video_dir):
                name, ext = os.path.splitext(f)
                if ext.lower() in config.VIDEO_EXTENSIONS:
                    # 存储小写化的文件名用于匹配
                    available_files[name.lower()] = os.path.join(video_dir, f)
        except Exception as e:
            logger.error(f"读取视频目录失败: {e}")
            return self._video_paths

        logger.info(f"视频目录中共发现 {len(available_files)} 个视频文件")

        # 为每个动作查找视频
        for action, keyword in config.VIDEO_MAPPING.items():
            filepath = self._find_video_for_action(action, keyword, available_files, video_dir)
            if filepath:
                self._video_paths[action] = filepath
                logger.info(f"  ✅ {action} → {os.path.basename(filepath)}")
            else:
                self._missing_actions.append(action)
                logger.warning(f"  ❌ 未找到 {action} 对应视频文件")

        return self._video_paths

    def _find_video_for_action(self, action, keyword, available_files, video_dir):
        """多层匹配查找视频文件"""
        # 1. 精确匹配（小写化）
        keyword_lower = keyword.lower()
        for ext in config.VIDEO_EXTENSIONS:
            exact_name = keyword_lower
            if exact_name in available_files:
                return available_files[exact_name]

        # 2. 关键词模糊匹配
        for name_lower, filepath in available_files.items():
            if keyword_lower in name_lower:
                return filepath

        # 3. 别名匹配
        aliases = config.VIDEO_ALIASES.get(action, [])
        for alias in aliases:
            alias_lower = alias.lower()
            # 精确别名匹配
            if alias_lower in available_files:
                return available_files[alias_lower]
            # 模糊别名匹配
            for name_lower, filepath in available_files.items():
                if alias_lower in name_lower:
                    return filepath

        # 4. 使用动作名直接匹配（兜底）
        action_lower = action.lower()
        for ext in config.VIDEO_EXTENSIONS:
            if action_lower in available_files:
                return available_files[action_lower]

        return None

    def get_media_content(self, filepath):
        """获取或创建媒体内容缓存"""
        if filepath not in self._media_cache:
            url = QUrl.fromLocalFile(os.path.abspath(filepath))
            self._media_cache[filepath] = QMediaContent(url)
        return self._media_cache[filepath]

    def clear_cache(self):
        """清空缓存"""
        self._media_cache.clear()

    def get_video_path(self, action):
        """获取动作对应的视频路径"""
        return self._video_paths.get(action)

    def has_video(self, action):
        """检查是否有可用视频"""
        return action in self._video_paths

    def report_error(self, action):
        """上报加载错误"""
        self._load_errors.add(action)

    def get_missing_actions(self):
        """获取缺失的动作列表"""
        return self._missing_actions

    def get_load_errors(self):
        """获取加载错误的动作列表"""
        return self._load_errors


class TransparentVideoSurface(QAbstractVideoSurface):
    """自定义视频表面：优化的帧处理"""
    frameReady = pyqtSignal(QImage)
    errorOccurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._format = None
        self._frame_count = 0
        self._dropped_frames = 0

    def present(self, frame):
        if not frame.isValid():
            return False

        try:
            frame.map(1)  # QAbstractVideoBuffer.ReadOnly
            try:
                self._frame_count += 1

                # 确定像素格式
                pixel_format = frame.pixelFormat()
                qimage_format = QImage.Format_RGB32
                try:
                    if pixel_format == QVideoFrame.Format_ARGB32:
                        qimage_format = QImage.Format_ARGB32
                    elif pixel_format == QVideoFrame.Format_ARGB32_Premultiplied:
                        qimage_format = QImage.Format_ARGB32_Premultiplied
                    elif pixel_format == QVideoFrame.Format_RGB24:
                        qimage_format = QImage.Format_RGB888
                except Exception:
                    pass

                # 创建并深拷贝图像
                image = QImage(
                    frame.bits(),
                    frame.width(),
                    frame.height(),
                    frame.bytesPerLine(),
                    qimage_format
                )
                copied = image.copy()
                self.frameReady.emit(copied)
            except Exception as e:
                logger.warning(f"帧转换错误: {e}")
            finally:
                frame.unmap()
        except Exception as e:
            logger.debug(f"帧处理错误: {e}")
        return True

    def start(self, format):
        self._format = format
        self._frame_count = 0
        return super().start(format)

    def supportedPixelFormats(self, handleType=0):
        formats = []
        for fmt_name in ['Format_RGB32', 'Format_ARGB32', 'Format_ARGB32_Premultiplied',
                         'Format_RGB24', 'Format_YUV420P', 'Format_NV12']:
            if hasattr(QVideoFrame, fmt_name):
                formats.append(getattr(QVideoFrame, fmt_name))
        return formats if formats else [0]

    def resetFrameCount(self):
        self._frame_count = 0

    def getFrameCount(self):
        return self._frame_count


class TransparentVideoWidget(QWidget):
    """透明视频显示控件：支持交叉淡入淡出过渡"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_image = None
        self._prev_image = None
        self._display_image = None
        self.setFixedSize(config.PET_SIZE, config.PET_SIZE)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

        # 过渡相关
        self._transition_alpha = 1.0
        self._transition_target = None
        self._is_transitioning = False

        # 待过渡标记：切换动作时设置，等新视频第一帧到达时触发交叉淡入淡出
        self._pending_transition = False
        self._pending_duration = 200

    def setFrame(self, image):
        """接收新帧：如果有待过渡标记，启动交叉淡入淡出"""
        if self._pending_transition and self._display_image and not self._display_image.isNull():
            # 第一帧新视频到达 → 启动交叉淡入淡出
            self._prev_image = self._display_image
            self._transition_target = image
            self._is_transitioning = True
            self._transition_alpha = 0.0
            self._pending_transition = False

            self._transition_anim = QPropertyAnimation(self, b"transition_alpha")
            self._transition_anim.setDuration(self._pending_duration)
            self._transition_anim.setStartValue(0.0)
            self._transition_anim.setEndValue(1.0)
            self._transition_anim.setEasingCurve(QEasingCurve.OutQuad)
            self._transition_anim.finished.connect(self._on_transition_finished)
            self._transition_anim.start()

        self._current_image = image
        self._display_image = image
        self.update()

    def schedule_transition(self, duration_ms=200):
        """标记下一次帧到达时启动过渡（旧帧保持显示直到新帧到达）"""
        self._pending_transition = True
        self._pending_duration = duration_ms

    def _on_transition_finished(self):
        self._is_transitioning = False
        self._prev_image = None
        self._transition_target = None
        self.update()

    def get_transition_alpha(self):
        return self._transition_alpha

    def set_transition_alpha(self, value):
        self._transition_alpha = value
        self.update()

    transition_alpha = property(get_transition_alpha, set_transition_alpha)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        scaled_size = config.PET_SIZE

        # 过渡模式
        if self._is_transitioning and self._prev_image and self._transition_target:
            alpha = self._transition_alpha

            # 前一帧淡出
            if self._prev_image and not self._prev_image.isNull():
                prev_scaled = self._prev_image.scaled(
                    scaled_size, scaled_size,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                painter.setOpacity(1.0 - alpha)
                x = (self.width() - prev_scaled.width()) // 2
                y = (self.height() - prev_scaled.height()) // 2
                painter.drawImage(x, y, prev_scaled)

            # 新帧淡入
            if self._transition_target and not self._transition_target.isNull():
                new_scaled = self._transition_target.scaled(
                    scaled_size, scaled_size,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                painter.setOpacity(alpha)
                x = (self.width() - new_scaled.width()) // 2
                y = (self.height() - new_scaled.height()) // 2
                painter.drawImage(x, y, new_scaled)

            painter.setOpacity(1.0)
        else:
            # 正常显示
            if self._display_image and not self._display_image.isNull():
                scaled = self._display_image.scaled(
                    scaled_size, scaled_size,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                painter.setOpacity(1.0)
                x = (self.width() - scaled.width()) // 2
                y = (self.height() - scaled.height()) // 2
                painter.drawImage(x, y, scaled)

        painter.end()


class BubbleWidget(QWidget):
    """头顶对话气泡：圆角半透明，支持跟随动画"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self._text = ""
        self._bubble_width = 0
        self._bubble_height = 0
        self._font = QFont("PingFang SC", 11)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start_fade_out)

        # 窗口透明度动画
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setWindowOpacity(0.0)
        self.hide()

        # 跟随猫咪位置
        self._anchor_offset = QPoint(0, -40)
        self._target_pos = QPoint(0, 0)

    def show_text(self, text, duration_ms=None, anchor_pos=None):
        """准备气泡文案和尺寸"""
        if not getattr(config, "BUBBLE_ENABLED", True) or not text:
            self.hide()
            return
        self._text = text

        font = QFont("PingFang SC", 11)
        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(text)
        text_height = fm.height()
        padding_x = 14
        padding_y = 10
        self._bubble_width = text_width + padding_x * 2
        self._bubble_height = text_height + padding_y * 2
        self._font = font
        self.resize(self._bubble_width + 4, self._bubble_height + 8)
        self.update()

        duration = duration_ms if duration_ms else getattr(config, "BUBBLE_DURATION_MS", 3500)
        self._timer.start(duration)

    def show_bubble(self, anchor_pos=None):
        """显示气泡：丝滑淡入"""
        self.show()
        self.raise_()
        self._fade_anim.stop()
        self._fade_anim.setDuration(250)
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()
        self.update()

    def position_near(self, target_pos):
        """定位到目标位置附近"""
        self._target_pos = target_pos
        self.move(target_pos)

    def _start_fade_out(self):
        """定时器到期 → 丝滑淡出"""
        self._fade_anim.stop()
        self._fade_anim.setDuration(400)
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self.hide)
        self._fade_anim.start()

    def hide(self):
        try:
            self._fade_anim.finished.disconnect()
        except (TypeError, RuntimeError):
            pass
        super().hide()

    def paintEvent(self, event):
        if not self._text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        bg = config.BUBBLE_BG_COLOR
        painter.setBrush(QColor(bg[0], bg[1], bg[2], bg[3]))
        painter.setPen(Qt.NoPen)
        radius = config.BUBBLE_ROUNDED_RADIUS
        bubble_rect = self.rect().adjusted(2, 2, -2, -8)
        painter.drawRoundedRect(bubble_rect, radius, radius)

        # 小三角指向猫咪
        triangle = [
            (self.width() // 2 - 6, bubble_rect.bottom()),
            (self.width() // 2 + 6, bubble_rect.bottom()),
            (self.width() // 2, bubble_rect.bottom() + 8),
        ]
        poly = QPolygonF([QPointF(*p) for p in triangle])
        painter.drawPolygon(poly)

        tc = config.BUBBLE_TEXT_COLOR
        painter.setPen(QColor(tc[0], tc[1], tc[2]))
        painter.setFont(self._font)
        painter.drawText(bubble_rect, Qt.AlignCenter, self._text)
        painter.end()


class PetWindow(QWidget):
    """桌面宠物主窗口"""

    def __init__(self):
        super().__init__()
        self._setup_base()
        self._setup_ui()
        self._setup_video_player()
        self._setup_data_dir()
        self._load_pet_name()
        self._setup_timers()
        self._apply_window_settings()
        self._show_missing_warning()
        self._load_video_for_idle()

    def _setup_base(self):
        """基础属性初始化"""
        self.setFixedSize(config.PET_SIZE, config.PET_SIZE)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )

        self._drag_offset = None
        self._is_dragging = False
        self._click_start_pos = None
        self._click_count = 0
        self._click_reset_timer = QTimer(self)
        self._click_reset_timer.setSingleShot(True)
        self._click_reset_timer.timeout.connect(self._on_click_window_expired)

        self._intimacy = 0
        self._last_chat_time = None
        self._focus_mode = False
        self._dnd_mode = False
        self._is_hovering = False
        self._last_interaction_time = 0
        self._focus_exit_pending = False  # 专注模式退出标记（布尔值）
        self._focus_exit_bubble_pending = False  # stretch 播完后弹气泡标记

        # 视频状态
        self._video_active = False
        self._current_action = "idle"
        self._loop_action = False
        self._media_error = False
        self._video_available = False
        self._waking_from_sleep = False
        self._failed_actions = set()
        self._event_queue = []
        self._last_rotation_time = 0
        self._lie_back_loop_count = 0
        self._video_load_retry = {}
        self._last_play_time = {}  # 动作冷却时间记录
        self._media_switching = False  # 媒体切换标记：切换期间忽略旧的 StoppedState

        # happy 循环标记：鼠标悬停或功能面板打开时持续播放 happy
        self._happy_loop = False
        self._panel_happy = False  # 功能面板打开时标记

        # gif 播放状态
        self._gif_movie = None       # QMovie 实例
        self._gif_label = None       # 隐藏 QLabel（QMovie 需要载体）
        self._is_gif = False         # 当前是否在播放 gif

        # 子窗口
        self._chat_window = None
        self._tools_panel = None
        # 毛玻璃举牌弹窗实例缓存（避免重复创建，关闭时清理）
        self._glass_dialogs = {}

        # 气泡
        self._bubble = BubbleWidget()
        self._bubble.hide()

        # 健康提醒环形进度条（猫咪头顶常驻，跟随猫咪头部移动）
        self._ring_widget = None
        self._ring_progress_map = {}

        # 视频管理器
        self._video_manager = VideoManager()

        # 帧监控
        self._frame_watchdog = QTimer(self)
        self._frame_watchdog.setSingleShot(True)
        self._frame_watchdog.timeout.connect(self._on_frame_watchdog)
        self._watchdog_action = None

    def _setup_ui(self):
        """初始化界面"""
        self._video_widget = TransparentVideoWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._video_widget)

    def _setup_video_player(self):
        """初始化视频播放器"""
        try:
            self._video_surface = TransparentVideoSurface()
            self._video_surface.frameReady.connect(self._video_widget.setFrame)
            self._video_surface.errorOccurred.connect(self._on_video_error)

            self._media_player = QMediaPlayer(self)
            self._media_player.setVideoOutput(self._video_surface)
            self._media_player.setMuted(True)  # 禁用背景音乐
            self._media_player.setVolume(0)
            self._media_player.stateChanged.connect(self._on_video_state_changed)
            self._media_player.mediaStatusChanged.connect(self._on_media_status_changed)
            self._media_player.error.connect(self._on_media_error)

            self._playlist = QMediaPlaylist()
            self._media_player.setPlaylist(self._playlist)

            self._video_available = True
            logger.info("视频播放器初始化成功")
        except Exception as e:
            logger.warning(f"视频播放器初始化失败: {e}")
            self._video_available = False
            self._media_player = None
            self._video_surface = None
            self._playlist = None

        self._video_paths = self._video_manager.scan_videos(config.VIDEO_DIR)

    def _setup_gif_player(self, filepath):
        """初始化 QMovie 播放 gif 动图，帧数据送入 TransparentVideoWidget"""
        self._stop_gif()
        self._gif_label = QLabel()
        self._gif_movie = QMovie(filepath)
        self._gif_movie.setCacheMode(QMovie.CacheAll)  # 预加载所有帧，保证流畅
        self._gif_label.setMovie(self._gif_movie)
        self._gif_movie.frameChanged.connect(self._on_gif_frame_changed)
        self._gif_movie.start()
        self._is_gif = True
        logger.info(f"[GIF] 开始播放: {os.path.basename(filepath)}")

    def _stop_gif(self):
        """停止并清理 gif 播放"""
        if self._gif_movie:
            try:
                self._gif_movie.frameChanged.disconnect(self._on_gif_frame_changed)
            except (TypeError, RuntimeError):
                pass
            self._gif_movie.stop()
            self._gif_movie = None
        if self._gif_label:
            self._gif_label.deleteLater()
            self._gif_label = None
        self._is_gif = False

    def _on_gif_frame_changed(self, frame_number):
        """gif 帧更新 → 提取 QImage 送入视频控件"""
        if not self._gif_movie or not self._is_gif:
            return
        pixmap = self._gif_movie.currentPixmap()
        if pixmap and not pixmap.isNull():
            image = pixmap.toImage()
            self._video_widget.setFrame(image)

    def _on_gif_short_done(self):
        """gif 短动画（happy）播放完成 → 回到 idle（仅非循环模式调用）"""
        if not self._is_gif or self._current_action != "happy":
            return
        if self._happy_loop:
            return  # 循环模式由 QMovie 原生无限循环，无需处理
        logger.info("[GIF] happy 短动画完成 → idle")
        self.play_action("idle", force=True)

    def _setup_data_dir(self):
        """创建数据目录"""
        os.makedirs(config.DATA_DIR, exist_ok=True)

    def _setup_timers(self):
        """初始化计时器"""
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle_timeout)
        self._idle_timer.start(config.IDLE_TIMEOUT)

        self._sleep_timer = QTimer(self)
        self._sleep_timer.setSingleShot(True)
        self._sleep_timer.timeout.connect(self._on_sleep_timeout)
        self._sleep_timer.start(config.SLEEP_TIMEOUT)

        self._no_chat_timer = QTimer(self)
        self._no_chat_timer.setSingleShot(True)
        self._no_chat_timer.timeout.connect(self._on_no_chat_timeout)
        self._no_chat_timer.start(config.LIE_SIDE_CHAT_TIMEOUT)

        self._auto_downgrade_timer = QTimer(self)
        self._auto_downgrade_timer.timeout.connect(self._on_auto_downgrade)
        self._auto_downgrade_timer.start(60000)

        # 提醒系统：久坐→stretch，喝水→eat（增强：总开关/自定义间隔/环形进度/队列/专注静默）
        self._reminder_system = ReminderSystem()
        self._reminder_system.reminder_triggered.connect(self._on_reminder_triggered)
        self._reminder_system.progress_updated.connect(self._on_ring_progress)
        self._reminder_system.queue_updated.connect(self._on_reminder_queue_updated)
        # 从持久化状态恢复总开关（重启不丢失）
        state = self._reminder_system.get_state()
        self._reminder_system.set_enabled(state.get("enabled", config.HEALTH_REMINDER_ENABLED))
        self._reminder_system.start()

        # 猫咪头顶环形进度条（常驻，跟随猫咪头部，展示距离下次提醒剩余时长）
        self._ring_widget = HealthRingWidget()
        self._ring_widget.follow(self)

        # idle 气泡轮换定时器：待机期间每 15 秒弹出不同气泡
        self._idle_bubble_timer = QTimer(self)
        self._idle_bubble_timer.setInterval(15000)
        self._idle_bubble_timer.timeout.connect(self._show_random_idle_bubble)
        self._idle_bubble_timer.start()

    def _apply_window_settings(self):
        """应用窗口置顶配置"""
        flags = self.windowFlags()
        if config.WINDOW_TOP_HINT:
            flags |= Qt.WindowStaysOnTopHint
        if config.WINDOW_INTERACT_THROUGH:
            flags |= Qt.WindowTransparentForInput
        self.setWindowFlags(flags)

        # 保存配置
        self._save_config()

    def _save_config(self):
        """保存窗口配置"""
        try:
            config_data = {
                "window_top_hint": config.WINDOW_TOP_HINT,
                "window_interact_through": config.WINDOW_INTERACT_THROUGH,
                "pos_x": self.x(),
                "pos_y": self.y(),
                "pet_name": config.PET_NAME,
                "version": "7.0.0"
            }
            with open(config.CONFIG_FILE, 'w') as f:
                json.dump(config_data, f, indent=2)
        except Exception as e:
            logger.debug(f"保存配置失败: {e}")

    def _load_pet_name(self):
        """从持久化配置恢复宠物姓名（默认「团子」）"""
        try:
            if os.path.exists(config.CONFIG_FILE):
                with open(config.CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                name = data.get("pet_name")
                if name and isinstance(name, str) and name.strip():
                    config.PET_NAME = name.strip()
        except Exception as e:
            logger.debug(f"读取宠物姓名失败: {e}")

    def _set_pet_name(self):
        """自定义宠物姓名：弹出自定义样式输入框 → 更新全局配置 + 持久化 + 同步托盘/对话窗"""
        dlg = QDialog(self)
        dlg.setWindowTitle("设置宠物姓名")
        dlg.setFixedSize(320, 160)
        dlg.setStyleSheet("""
            QDialog { background-color: rgba(255, 228, 235, 235); }
            QLabel { color: #6E6E6E; font-family: "PingFang SC", "Microsoft YaHei"; font-size: 13px; }
            QLineEdit {
                border: 1px solid rgba(255, 182, 193, 200);
                padding: 6px;
                background: white;
                color: #4A4A4A;
                font-size: 13px;
            }
            QPushButton {
                border: 1px solid rgba(255, 182, 193, 180);
                padding: 6px 18px;
                background-color: rgba(255, 182, 193, 180);
                color: #6E6E6E;
                font-family: "PingFang SC", "Microsoft YaHei";
                font-size: 13px;
            }
            QPushButton:hover { background-color: rgba(255, 150, 170, 220); }
        """)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)
        label = QLabel("请输入新的名字：")
        layout.addWidget(label)
        input_field = QLineEdit(config.PET_NAME)
        layout.addWidget(input_field)
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("确定")
        btn_cancel = QPushButton("取消")
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        if dlg.exec_() != QDialog.Accepted:
            return
        new_name = input_field.text().strip()
        if not new_name:
            return
        config.PET_NAME = new_name
        self._save_config()
        # 同步已打开的 AI 对话窗（更新 system prompt 与标题）
        try:
            if self._chat_window is not None and hasattr(self._chat_window, "update_pet_name"):
                self._chat_window.update_pet_name(new_name)
        except Exception:
            pass
        logger.info(f"宠物姓名已更新: {new_name}")

    def _show_missing_warning(self):
        """显示素材缺失提示"""
        missing = self._video_manager.get_missing_actions()
        if missing:
            logger.warning(f"⚠️  缺失视频: {', '.join(missing)}")
            logger.info("   请将对应视频文件放入: assets/video/")
            logger.info("   或使用默认格式: {action}.mov / {action}.mp4")

            # 关键动作缺失 → 延迟弹窗提示用户
            critical = {"eat", "stretch", "happy"}
            missing_critical = [a for a in missing if a in critical]
            if missing_critical:
                QTimer.singleShot(1500, lambda: self._show_missing_popup(missing))

    def _show_missing_popup(self, missing):
        """弹出素材缺失警告"""
        names = {
            "eat": "喝水(eat)", "stretch": "伸懒腰(stretch)",
            "happy": "开心(happy)",
            "idle": "待机(idle)",
            "lie_back": "平躺(lie_back)", "lie_side": "侧躺(lie_side)",
            "sleep": "睡觉(sleep)",
        }
        detail = "\n".join(f"  ❌ {names.get(a, a)}" for a in missing)
        QMessageBox.warning(
            self, "视频素材缺失",
            f"以下动作缺少视频文件，将使用替代动画：\n\n{detail}\n\n"
            f"请将对应视频放入 assets/video/ 目录\n"
            f"文件名参考: eat.mp4 / stretch.mp4 / happy.mp4 等\n"
            f"也支持中文命名: 喝水.mp4 / 伸懒腰.mp4"
        )

    def _load_video_for_idle(self):
        """启动时加载待机视频"""
        if self._video_available and self._video_paths:
            QTimer.singleShot(300, lambda: self.play_action("idle", force=True))
        else:
            logger.warning("⚠️ 未找到视频文件，宠物将不显示动画")

    def _get_playable_action(self, action_name):
        """获取实际可播放的动作（带详细日志）"""
        fallback_list = FALLBACK_ACTIONS.get(action_name, [action_name])
        for act in fallback_list:
            if act in self._failed_actions:
                logger.debug(f"  [fallback] 跳过 '{act}'（已标记失败）")
                continue
            if self._video_manager.has_video(act):
                if act != action_name:
                    logger.info(f"  [fallback] '{action_name}' 无视频 → 使用 '{act}'")
                return act
            else:
                logger.debug(f"  [fallback] '{act}' 无视频文件")
        logger.warning(f"  [fallback] '{action_name}' 所有候选均无可用视频: {fallback_list}")
        return None

    def _can_play(self, action_name):
        """检查是否可以播放该动作（返回 (bool, reason) 元组，支持柔性队列）"""
        import time

        # sleep 屏蔽主动交互
        if self._current_action == "sleep":
            if action_name not in ("idle", "lie_side"):
                logger.info(f"[互斥] sleep 屏蔽: {action_name}")
                return False, "sleep熟睡屏蔽主动交互"

        # 优先级检查（柔性：低优先级动作入队等待，而非直接拒绝）
        target_priority = config.ACTION_PRIORITY.get(action_name, 1)
        current_priority = config.ACTION_PRIORITY.get(self._current_action, 1)
        if target_priority < current_priority:
            logger.info(f"[优先级] {action_name}({target_priority}) 不可打断 {self._current_action}({current_priority})")
            return False, f"优先级不足 {target_priority}<{current_priority}"

        # 冷却检查
        cooldown = config.ACTION_COOLDOWN.get(action_name, 0)
        if cooldown > 0:
            last_time = self._last_play_time.get(action_name, 0)
            elapsed_ms = (time.time() - last_time) * 1000
            if elapsed_ms < cooldown:
                return False, f"冷却中({int((cooldown-elapsed_ms)/1000)}s)"

        return True, "OK"

    def _play_focus_exit_sequence(self):
        """专注模式退出专属交互：强制播放 stretch，播完后弹气泡 + 丝滑过渡到 idle"""
        logger.info("专注模式退出 → 播放 stretch 伸懒腰（播完后弹气泡 + 过渡到 idle）")
        self._focus_exit_pending = True
        # 标记：stretch 播完后需要弹气泡（在 _on_video_state_changed 中触发）
        self._focus_exit_bubble_pending = True
        # 切换前先停止当前循环动作（lie_side/sleep），避免旧循环的 EndOfMedia 干扰 stretch 完成
        # 关键：先置位 _media_switching，屏蔽 stop() 同步触发的 StoppedState
        # 否则该 StoppedState 会进入 else 分支，误判"stretch 已完成"而提前弹气泡 + 播放 idle
        try:
            if self._media_player:
                self._loop_action = False  # 先关闭循环标记，防止旧动作的 EndOfMedia 触发重启逻辑
                self._media_switching = True  # 屏蔽 stop() 产生的 StoppedState
                self._media_player.stop()
        except Exception:
            self._media_switching = False
        # 延迟 150ms 再播放 stretch，确保旧解码器完全释放
        # （macOS AVFoundation 的 stop() 是异步的，立即 play() 新媒体可能静默失败）
        QTimer.singleShot(150, lambda: self.play_action("stretch", force=True))

    def _show_focus_exit_bubble(self):
        """显示专注模式退出气泡：从专属文案与随机文案中随机切换"""
        # 专属文案 + 随机切换文案，退出专注时随机播放其一
        candidates = [config.FOCUS_EXIT_BUBBLE_TEXT] + config.ACTION_BUBBLE_TEXTS.get("stretch", [])
        text = random.choice(candidates) if candidates else config.FOCUS_EXIT_BUBBLE_TEXT
        self._bubble.hide()
        self._bubble.show_text(text, duration_ms=4000)
        pos = self._position_for_bubble()
        self._bubble.position_near(pos)
        self._bubble.show_bubble()
        logger.info(f"[专注退出] 显示气泡: {text}")

    def _position_for_bubble(self):
        """计算气泡位置（猫咪头部右上方）"""
        pet_pos = self.pos()
        bubble_x = pet_pos.x() + self.width() // 2 - 30
        bubble_y = pet_pos.y() - 50
        return QPoint(bubble_x, bubble_y)

    def play_action(self, action_name, force=False):
        """播放指定动作的视频（柔性队列设计：优先级不足时入队等待，不粗暴拒绝）"""
        if not force and action_name != "idle":
            can, reason = self._can_play(action_name)
            if not can:
                # 柔性设计：不直接拒绝，而是加入事件队列等待当前动画播完
                if reason and "优先级" in reason:
                    logger.info(f"[柔性队列] {action_name} 入队等待（{reason}）")
                    self._event_queue.append((action_name, force, 0))
                    return True  # 返回True表示已接受（排队中）
                logger.info(f"[跳过] {action_name}: {reason}")
                return False

        import time
        self._last_play_time[action_name] = time.time()

        # 获取可播放的动作
        playable = self._get_playable_action(action_name)
        if playable is None:
            logger.error(f"❌ 无可播放视频: {action_name}")
            return False

        if playable != action_name:
            logger.info(f"🔄 替代: '{action_name}' → '{playable}'")

        filepath = self._video_manager.get_video_path(playable)
        if not filepath:
            logger.error(f"❌ 视频路径为空: {playable}")
            return False

        # 判断是否为 gif 文件
        is_gif = filepath.lower().endswith(".gif")

        if is_gif and not self._video_available:
            # gif 不需要 QMediaPlayer，直接走 QMovie 路径
            pass
        elif not is_gif and not self._video_available:
            return False

        # 保存旧动作（用于过渡判断）
        prev_action = self._current_action

        logger.info(f"▶️ 播放: {action_name}→{playable} ({config.ACTION_PRIORITY.get(action_name, 1)}) {'[GIF]' if is_gif else ''}")

        self._current_action = action_name
        self._loop_action = action_name in LOOP_ACTIONS

        # 安排过渡动画：旧帧保持显示，新动作第一帧到达时交叉淡入淡出
        if prev_action != action_name and self._video_widget._display_image:
            transition_ms = config.TRANSITION_LONG_MS
            if action_name in SHORT_ACTIONS:
                transition_ms = config.TRANSITION_SHORT_MS
            if self._focus_exit_pending:
                transition_ms = config.TRANSITION_FOCUS_EXIT_MS
            self._video_widget.schedule_transition(transition_ms)

        if is_gif:
            # ─── gif 路径：使用 QMovie 播放 ───
            # 先置位切换标记，屏蔽 stop() 产生的 StoppedState（否则会泄漏到循环逻辑导致掉帧）
            self._media_switching = True
            if self._media_player:
                self._media_player.stop()
            self._video_active = True
            self._media_error = False
            self._setup_gif_player(filepath)
            # _is_gif 已设为 True，StoppedState 会被 gif 守卫拦截，安全清除标记
            self._media_switching = False

            # 短动画（happy）：非循环模式时播放一轮后回 idle
            if action_name in SHORT_ACTIONS and not self._happy_loop:
                QTimer.singleShot(2500, self._on_gif_short_done)
        else:
            # ─── mp4 路径：使用 QMediaPlayer 播放 ───
            self._stop_gif()  # 停止旧的 gif（如果有）

            # 媒体切换标记：切换期间忽略旧的 StoppedState
            self._media_switching = True

            # 设置媒体
            content = self._video_manager.get_media_content(filepath)
            self._playlist.clear()
            self._playlist.addMedia(content)

            # 统一使用 CurrentItemOnce；循环动作在 EndOfMedia 时手动 setPosition(0)+play 无缝重启
            self._playlist.setPlaybackMode(QMediaPlaylist.CurrentItemOnce)

            self._video_active = True
            self._media_error = False

            if self._video_surface:
                self._video_surface.resetFrameCount()

            self._watchdog_action = action_name
            self._frame_watchdog.start(2000)

            self._media_player.play()

        if action_name == "lie_back":
            self._lie_back_loop_count = 1
        else:
            self._lie_back_loop_count = 0

        # 气泡
        self._show_bubble_for_action(action_name)

        return True

    def _show_bubble_for_action(self, action_name):
        """显示动作气泡：动作播放 0.5s 后弹出，跟随猫咪头部移动"""
        # 专注退出过渡期间不显示 idle 气泡，避免覆盖"我睡醒啦！"专属气泡
        if self._focus_exit_pending:
            return
        # 功能面板打开时由 _open_glass_dialog 弹出功能相关气泡，跳过 happy 动作自身气泡
        if action_name == "happy" and self._panel_happy:
            return

        texts = config.ACTION_BUBBLE_TEXTS.get(action_name, [])
        if not texts:
            return

        text = random.choice(texts)
        # 延迟 0.5s 弹出气泡（动作播放至 0.5s 时显示）
        delay = getattr(config, "BUBBLE_SHOW_DELAY_MS", 500)
        QTimer.singleShot(delay, lambda: self._do_show_bubble(text, action_name))

    def _do_show_bubble(self, text, action_name):
        """实际弹出气泡（跟随猫咪头部位置）"""
        self._bubble.hide()
        self._bubble.show_text(text)
        pos = self._position_for_bubble()
        self._bubble.position_near(pos)
        self._bubble.show_bubble()
        logger.info(f"[气泡] {action_name}: '{text}'")

    def _show_random_idle_bubble(self):
        """idle 待机期间随机弹出不同气泡内容"""
        if self._current_action == "idle" and not self._focus_mode and not self._dnd_mode:
            texts = config.ACTION_BUBBLE_TEXTS.get("idle", [])
            if texts:
                text = random.choice(texts)
                self._do_show_bubble(text, "idle")

    def _position_bubble(self):
        """定位气泡位置"""
        pos = self._position_for_bubble()
        self._bubble.position_near(pos)

    def _process_event_queue(self):
        """处理事件队列"""
        if not self._event_queue:
            return
        action_name, force, _ = self._event_queue.pop(0)
        logger.info(f"[队列] 出队: {action_name}")
        self.play_action(action_name, force=force)

    def _on_video_state_changed(self, state):
        """视频播放结束处理"""
        if state != QMediaPlayer.StoppedState:
            return
        if self._is_gif:
            return  # gif 不使用 QMediaPlayer，忽略残留的 StoppedState
        if not self._video_active or self._media_error:
            return
        # 媒体切换期间忽略旧的 StoppedState（防止旧视频停止触发新动作的完成回调）
        if self._media_switching:
            logger.debug("[媒体切换] 忽略旧视频 StoppedState")
            return

        if self._waking_from_sleep:
            logger.info("唤醒 → idle")
            self._waking_from_sleep = False
            self.play_action("idle", force=True)
        elif self._current_action == "lie_back":
            self._lie_back_loop_count += 1
            if self._lie_back_loop_count >= config.LIE_BACK_LOOP_COUNT:
                logger.info("lie_back 循环完成 → idle")
                self._lie_back_loop_count = 0
                self.play_action("idle", force=True)
                if self._event_queue:
                    QTimer.singleShot(200, self._process_event_queue)
            else:
                # 无缝重启：setPosition(0)+play 避免解码器重新加载导致跳帧
                try:
                    self._media_switching = True
                    self._media_player.play()
                    self._media_player.setPosition(0)
                    self._media_switching = False
                except Exception as e:
                    logger.warning(f"lie_back 循环重启失败: {e}")
                    self._media_switching = False
        elif self._loop_action:
            # idle/sleep/lie_side 循环动作：无缝重启
            # 先 play() 恢复播放状态，再 setPosition(0) seek 到开头
            # （若先 setPosition 再 play，macOS AVFoundation 会 stop→reload 解码器导致卡顿）
            logger.debug(f"[循环] {self._current_action} StoppedState → play+setPosition(0) 无缝重启")
            try:
                self._media_switching = True  # 短暂屏蔽重启过程中的状态信号
                self._media_player.play()
                self._media_player.setPosition(0)
                self._media_switching = False
            except Exception as e:
                logger.warning(f"循环重启失败: {e}")
                self._media_switching = False
        else:
            logger.info(f"动作 '{self._current_action}' 播放完成")
            # happy 循环：鼠标悬停或功能面板打开时持续播放
            if self._current_action == "happy" and self._happy_loop:
                logger.debug("[happy循环] 重播 happy")
                self._media_player.setPosition(0)
                self._media_player.play()
                return
            # 专注模式退出：stretch 播完 → 先弹气泡 → 再丝滑过渡到 idle
            if self._focus_exit_pending:
                logger.info("专注退出 stretch 完成 → 弹气泡 + 丝滑过渡到 idle")
                # 1. 弹出专属气泡
                if self._focus_exit_bubble_pending:
                    self._focus_exit_bubble_pending = False
                    self._show_focus_exit_bubble()
                # 2. 丝滑过渡到 idle（此时 _focus_exit_pending 仍为 True，
                #    确保 transition 使用 TRANSITION_FOCUS_EXIT_MS），之后清除标记
                self.play_action("idle", force=True)
                self._focus_exit_pending = False
            elif self._dnd_mode:
                self.play_action("sleep", force=True)
            elif self._focus_mode:
                self.play_action("lie_side", force=True)
            else:
                self.play_action("idle", force=True)
            if self._event_queue:
                QTimer.singleShot(200, self._process_event_queue)

    def _on_media_status_changed(self, status):
        status_names = {
            QMediaPlayer.NoMedia: "无媒体",
            QMediaPlayer.LoadingMedia: "加载中",
            QMediaPlayer.LoadedMedia: "已加载",
            QMediaPlayer.BufferedMedia: "已缓冲",
            QMediaPlayer.StalledMedia: "停滞",
            QMediaPlayer.EndOfMedia: "结束",
            QMediaPlayer.InvalidMedia: "无效",
        }
        status_text = status_names.get(status, str(status))
        # 新媒体加载完成 → 清除切换标记，后续 StoppedState 才是真正的播放结束
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            self._media_switching = False
            logger.debug(f"媒体状态: {status_text}")
        elif status == QMediaPlayer.EndOfMedia:
            # 循环动作：在 EndOfMedia 时直接 setPosition(0)+play 实现无缝循环
            # 避免 StoppedState 导致解码器重新加载，消除首尾帧卡顿
            if self._loop_action and self._video_active and not self._media_error:
                logger.debug(f"[循环] {self._current_action} EndOfMedia → setPosition(0)+play 无缝重启")
                try:
                    self._media_switching = True
                    self._media_player.setPosition(0)
                    self._media_player.play()
                    self._media_switching = False
                except Exception as e:
                    logger.warning(f"无缝循环失败: {e}")
                    self._media_switching = False
            # 非循环动作的完成回调由 stateChanged(StoppedState) 处理
        elif status == QMediaPlayer.InvalidMedia:
            logger.warning(f"媒体无效: {status_text}")
            self._media_switching = False

    def _on_media_error(self, error):
        error_msg = self._media_player.errorString()
        logger.error(f"❌ 媒体错误: {error_msg}")
        self._media_error = True
        self._video_active = False
        # 清除切换标记，防止后续 StoppedState 被永久屏蔽
        self._media_switching = False

        # 重试机制
        action = self._current_action
        retries = self._video_load_retry.get(action, 0)
        if retries < config.VIDEO_LOAD_RETRY_COUNT:
            self._video_load_retry[action] = retries + 1
            logger.info(f"🔄 重试 {retries + 1}/{config.VIDEO_LOAD_RETRY_COUNT}: {action}")
            QTimer.singleShot(config.VIDEO_LOAD_RETRY_DELAY_MS,
                             lambda: self.play_action(action, force=True))
        else:
            # 重试失败，回退到 idle
            logger.warning(f"❌ 重试失败，回退 idle: {action}")
            self._failed_actions.add(action)
            self._video_load_retry[action] = 0
            QTimer.singleShot(500, lambda: self.play_action("idle", force=True))

    def _on_video_error(self, error_msg):
        logger.error(f"视频表面错误: {error_msg}")

    def _on_frame_watchdog(self):
        """帧监控：检测视频是否正在播放"""
        if self._video_active and self._video_surface:
            frame_count = self._video_surface.getFrameCount()
            if frame_count == 0:
                logger.warning(f"⚠️ 无帧接收，尝试恢复: {self._watchdog_action}")
                if self._watchdog_action:
                    # 清除切换标记后再重启，防止 StoppedState 被屏蔽
                    self._media_switching = False
                    self._media_player.stop()
                    self._playlist.setCurrentIndex(0)
                    self._media_player.play()

    def _on_idle_timeout(self):
        """30秒无操作 → idle"""
        if self._dnd_mode:
            return
        if self._focus_mode:
            if self._current_action != "lie_side":
                self.play_action(config.EVENT_ACTION_MAP.get("on_focus_mode", "lie_side"))
            return
        if self._current_action in ("idle", "sleep", "lie_side", "lie_back"):
            return
        self.play_action(config.EVENT_ACTION_MAP.get("on_idle_short", "idle"))

    def _on_sleep_timeout(self):
        """5分钟无操作 → sleep"""
        if self._dnd_mode:
            if self._current_action != "sleep":
                self.play_action("sleep", force=True)
            return
        if self._focus_mode:
            return
        self.play_action("sleep", force=True)

    def _on_no_chat_timeout(self):
        """长时间未对话 → lie_side"""
        if not self._focus_mode and not self._dnd_mode:
            self.play_action("lie_side", force=True)

    def _on_auto_downgrade(self):
        """状态自动降级"""
        # 简化：每60秒检查一次
        pass

    def _on_reminder_triggered(self, reminder_type, message):
        """提醒触发：强制播放对应动作 + 立即弹出气泡（不延迟）"""
        logger.info(f"[提醒] {reminder_type}: {message}")

        # 强制播放对应动作（喝水→eat，久坐→stretch）
        if reminder_type == "water":
            self.play_action("eat", force=True)
            bubble_texts = config.WATER_REMINDER_BUBBLES
        elif reminder_type == "sit":
            self.play_action("stretch", force=True)
            bubble_texts = config.SIT_REMINDER_BUBBLES
        else:
            bubble_texts = [message]

        # 立即弹出提醒气泡（不延迟）
        remind_text = random.choice(bubble_texts) if bubble_texts else message
        self._show_temp_bubble(remind_text, 3500)

        # 弹出举牌式提醒面板（毛玻璃，跟随猫咪头部，0.15s 淡入）
        dialog = ReminderActionGlassDialog(reminder_type, remind_text, parent_window=self)
        dialog.attach_to_pet(self)
        dialog.done_requested.connect(self._on_reminder_done)
        dialog.snooze_requested.connect(
            lambda rtype: self._reminder_system.snooze(rtype, remind_text)
        )
        dialog.fade_in()

    def _on_reminder_done(self, reminder_type):
        """用户点击「已完成喝水/已起身活动」：打卡记录 + happy 挥手 + 反馈气泡"""
        if self._reminder_system:
            self._reminder_system.log_checkin(reminder_type)
        # 切换 happy 挥手动画
        self.play_action("happy", force=True)
        # 反馈气泡
        if reminder_type == "water":
            self._show_temp_bubble(config.WATER_DONE_BUBBLE, 3500)
        elif reminder_type == "sit":
            self._show_temp_bubble(config.SIT_DONE_BUBBLE, 3500)

    def _water_checkin(self):
        """手动喝水打卡：播放喝水动画 + 计入今日饮水次数 + 反馈气泡"""
        # 播放喝水动画
        self._play_action_with_feedback("eat", "喝水")
        # 计入今日饮水打卡次数（用户主动打卡也计数）
        if self._reminder_system:
            self._reminder_system.log_checkin("water")
        # 反馈气泡
        self._show_temp_bubble(config.WATER_DONE_BUBBLE, 2500)
        logger.info("[喝水打卡] 用户手动打卡，今日饮水次数已 +1")

    def _on_ring_progress(self, reminder_type, progress):
        """环形进度条更新：显示当前最近到期（进度最高）的提醒剩余时长"""
        if self._ring_widget is None:
            return
        self._ring_progress_map[reminder_type] = progress
        # 总开关关闭时不显示进度环
        if self._reminder_system and not self._reminder_system.get_state().get("enabled", True):
            self._ring_widget.set_visible_type(None)
            return
        if not self._ring_progress_map:
            self._ring_widget.set_visible_type(None)
            return
        best_type = max(self._ring_progress_map, key=lambda k: self._ring_progress_map[k])
        best_prog = self._ring_progress_map[best_type]
        if best_prog <= 0.0:
            self._ring_widget.set_visible_type(None)
        else:
            self._ring_widget.set_visible_type(best_type)
            self._ring_widget.set_progress(best_prog)

    def _on_reminder_queue_updated(self, queue):
        """提醒队列更新（专注静默期间累积），仅记录日志，专注退出时统一释放"""
        if queue:
            logger.info(f"[提醒队列] 专注静默期间待处理: {queue}")

    def _show_temp_bubble(self, text, duration_ms=3500):
        """显示临时气泡（用于打卡反馈、计算完成等），跟随猫咪头部"""
        self._bubble.hide()
        self._bubble.show_text(text, duration_ms=duration_ms)
        pos = self._position_for_bubble()
        self._bubble.position_near(pos)
        self._bubble.show_bubble()
        logger.info(f"[气泡] 临时: '{text}'")

    # ========== 毛玻璃举牌弹窗接入 ==========

    def _open_glass_dialog(self, key, dialog_factory):
        """统一打开毛玻璃举牌弹窗：避免重复打开，跟随猫咪头部，弹簧淡入"""
        # 若已存在且可见，则关闭它（切换效果）
        dlg = self._glass_dialogs.get(key)
        if dlg is not None:
            try:
                if dlg.isVisible():
                    dlg.fade_out()
                    return
            except Exception:
                pass
        dlg = dialog_factory()
        dlg.attach_to_pet(self)
        dlg.closed.connect(lambda: self._on_glass_dialog_closed(key))
        self._glass_dialogs[key] = dlg
        # 举牌动画：循环播放 happy 直到面板关闭，专注/免打扰模式下不打断
        if not self._focus_mode and not self._dnd_mode:
            self._panel_happy = True
            self._happy_loop = True
            self.play_action("happy", force=True)
        # 弹出与功能相关的气泡文案
        bubble_text = getattr(config, "TOOL_PANEL_BUBBLES", {}).get(key)
        if bubble_text:
            self._show_temp_bubble(bubble_text, 4000)
        dlg.fade_in()

    def _on_glass_dialog_closed(self, key):
        """毛玻璃弹窗关闭：清理引用 + 停止 happy 循环"""
        self._glass_dialogs.pop(key, None)
        self._panel_happy = False
        if not self._is_hovering:
            self._happy_loop = False
            if self._current_action == "happy":
                self.play_action("idle", force=True)

    def _open_todo(self):
        """打开待办清单（毛玻璃举牌弹窗）"""
        self._open_glass_dialog("todo", lambda: TodoGlassDialog(parent_window=self))

    def _open_calculator(self):
        """打开计算器（支持键盘输入，计算完成弹气泡）"""
        def factory():
            dlg = CalculatorGlassDialog(parent_window=self)
            dlg.calc_done.connect(
                lambda r: self._show_temp_bubble(config.CALC_DONE_BUBBLE, 2500)
            )
            return dlg
        self._open_glass_dialog("calc", factory)

    def _open_notes(self):
        """打开随笔记事本（自动本地保存）"""
        self._open_glass_dialog("notes", lambda: NotesGlassDialog(parent_window=self))

    def _open_shortcuts(self):
        """打开 Mac 快捷键面板"""
        self._open_glass_dialog("shortcuts", lambda: ShortcutGlassDialog(parent_window=self))

    def _open_reminder_settings(self):
        """打开健康提醒设置面板（滑块自定义间隔 + 总开关）"""
        def factory():
            dlg = ReminderSettingGlassDialog(parent_window=self)
            if self._reminder_system:
                dlg.set_water_count(self._reminder_system.get_water_count_today())
            dlg.settings_changed.connect(self._on_reminder_settings_changed)
            return dlg
        self._open_glass_dialog("reminder_settings", factory)

    def _on_reminder_settings_changed(self, settings):
        """应用健康提醒设置（总开关 + 自定义间隔，持久化）"""
        if not self._reminder_system:
            return
        enabled = settings.get("enabled", config.HEALTH_REMINDER_ENABLED)
        sit_minutes = settings.get("sit_minutes", config.SIT_REMINDER_INTERVAL)
        water_minutes = settings.get("water_minutes", config.WATER_REMINDER_INTERVAL)
        self._reminder_system.set_enabled(enabled)
        self._reminder_system.update_intervals(sit_minutes, water_minutes)
        logger.info(f"[健康提醒] 设置已更新: 总开关={enabled}, 久坐={sit_minutes}min, 喝水={water_minutes}min")

    def _toggle_health_reminder(self):
        """切换健康提醒总开关（右键菜单一键开关）"""
        if not self._reminder_system:
            return
        state = self._reminder_system.get_state()
        new_enabled = not state.get("enabled", config.HEALTH_REMINDER_ENABLED)
        self._reminder_system.set_enabled(new_enabled)
        logger.info(f"[健康提醒] 总开关: {new_enabled}")

    def _on_click_window_expired(self):
        """点击窗口到期：区分单击/双击"""
        count = self._click_count
        self._click_count = 0
        if count == 2:
            logger.info("双击 → 打开 AI 对话")
            self.open_chat()

    def _wake_from_sleep(self):
        """从 sleep 唤醒 → stretch 伸懒腰"""
        self._waking_from_sleep = True
        self.play_action("stretch", force=True)

    def _increase_intimacy(self, amount=1):
        """增加亲密度"""
        self._intimacy += amount

    # ========== 焦点模式控制 ==========

    def set_focus_mode(self, enabled):
        """设置轻度专注模式（lie_side 侧躺陪伴）"""
        if self._focus_mode == enabled and not self._dnd_mode == enabled:
            # 当前已在目标状态且不在另一模式中
            if enabled and not self._dnd_mode:
                return
            if not enabled and not self._dnd_mode:
                return

        if enabled:
            self._dnd_mode = False  # 互斥：清除深度专注
            self._focus_mode = True
            logger.info("开启轻度专注 → lie_side")
            # 专注模式：健康提醒低优先级静默倒计时，不弹窗打断专注
            if self._reminder_system:
                self._reminder_system.set_focus_silenced(True)
            self.play_action("lie_side", force=True)
        else:
            logger.info("关闭轻度专注 → stretch 伸懒腰")
            self._focus_mode = False
            # 专注退出：恢复健康提醒，柔性释放静默期间累积的提醒队列
            if self._reminder_system:
                self._reminder_system.set_focus_silenced(False)
                self._reminder_system.release_pending()
            # 触发专注模式退出序列
            self._play_focus_exit_sequence()

    def set_dnd_mode(self, enabled):
        """设置深度专注模式（sleep 熟睡）"""
        if self._dnd_mode == enabled and not self._focus_mode == enabled:
            if enabled and not self._focus_mode:
                return
            if not enabled and not self._focus_mode:
                return

        if enabled:
            self._focus_mode = False  # 互斥：清除轻度专注
            self._dnd_mode = True
            logger.info("开启深度专注 → sleep")
            # 深度专注：健康提醒静默倒计时，不弹窗打断
            if self._reminder_system:
                self._reminder_system.set_focus_silenced(True)
            self.play_action("sleep", force=True)
        else:
            logger.info("关闭深度专注 → stretch 伸懒腰")
            self._dnd_mode = False
            # 专注退出：恢复健康提醒，柔性释放静默期间累积的提醒队列
            if self._reminder_system:
                self._reminder_system.set_focus_silenced(False)
                self._reminder_system.release_pending()
            # 触发专注模式退出序列
            self._play_focus_exit_sequence()

    # ========== AI 对话 ==========

    def open_chat(self):
        """打开 AI 对话窗口"""
        if self._chat_window is None:
            self._chat_window = ChatWindow()
        self._chat_window.show()
        self._chat_window.raise_()
        self._chat_window.activateWindow()
        import time
        self._last_chat_time = time.time()
        self._no_chat_timer.start(config.LIE_SIDE_CHAT_TIMEOUT)
        if self._focus_mode or self._dnd_mode:
            logger.info("[专注模式] 打开 AI 对话")
        elif self._current_action == "sleep":
            self._wake_from_sleep()
        import time as tm
        self._last_interaction_time = tm.time()
        self._idle_timer.start(config.IDLE_TIMEOUT)
        self._sleep_timer.start(config.SLEEP_TIMEOUT)

    def open_tools(self):
        """打开工具面板"""
        if self._tools_panel is None:
            self._tools_panel = ToolsPanel()
        self._tools_panel.show()
        self._tools_panel.raise_()
        self._tools_panel.activateWindow()

    def _manual_exit_focus(self):
        """手动退出专注模式：与系统自动关闭共用 stretch 伸懒腰逻辑"""
        if self._focus_mode:
            self.set_focus_mode(False)
        elif self._dnd_mode:
            self.set_dnd_mode(False)

    def _play_action_with_feedback(self, action_name, display_name=None):
        """播放动作并给出用户反馈：视频缺失时弹窗提示而非静默回退"""
        if not display_name:
            display_name = action_name
        # 检查是否有可用视频（含 fallback）
        playable = self._get_playable_action(action_name)
        if playable is None:
            aliases = config.VIDEO_ALIASES.get(action_name, [])
            alias_hint = " / ".join(aliases[:3]) if aliases else action_name
            QMessageBox.warning(
                self, "视频素材缺失",
                f"未找到「{display_name}」对应的视频文件。\n\n"
                f"请将视频放入 assets/video/ 目录，\n"
                f"文件名可参考: {alias_hint}.mp4\n\n"
                f"当前将播放替代动画。"
            )
            # 仍然尝试播放（可能 fallback 到 idle）
            self.play_action(action_name, force=True)
            return

        # 有视频 → 正常播放
        if playable != action_name:
            logger.info(f"  [打卡] '{display_name}' 使用替代视频: {playable}")
        self.play_action(action_name, force=True)

    # ========== 鼠标事件 ==========

    def enterEvent(self, event):
        """鼠标悬浮 → 持续播放 happy 开心动画"""
        self._is_hovering = True
        if self._focus_mode or self._dnd_mode:
            event.accept()
            return
        if self._current_action == "sleep":
            self._wake_from_sleep()
            event.accept()
            return
        # lie_back 撒娇播放期间不被悬停打断
        if self._current_action == "lie_back":
            event.accept()
            return
        if self._current_action in ("idle", "lie_side"):
            self._happy_loop = True
            self.play_action("happy", force=True)
        event.accept()

    def leaveEvent(self, event):
        """鼠标离开 → 恢复待机默认动作"""
        self._is_hovering = False
        if self._focus_mode or self._dnd_mode:
            event.accept()
            return
        # lie_back 撑娇播放期间不被离开打断，播放完自动回 idle
        if self._current_action == "lie_back":
            event.accept()
            return
        if self._current_action == "happy" and not self._panel_happy:
            self._happy_loop = False
            self.play_action("idle", force=True)
        event.accept()

    def mousePressEvent(self, event):
        """鼠标按下：拖拽全场景生效"""
        if event.button() == Qt.LeftButton:
            self._click_start_pos = event.pos()
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            self._is_dragging = False
            event.accept()

    def mouseMoveEvent(self, event):
        """拖拽移动"""
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            if not self._is_dragging:
                delta = event.pos() - self._click_start_pos
                if delta.manhattanLength() > 5:
                    self._is_dragging = True
            self.move(event.globalPos() - self._drag_offset)
            # 气泡跟随
            self._position_bubble()
            event.accept()

    def mouseReleaseEvent(self, event):
        """鼠标释放"""
        if event.button() != Qt.LeftButton:
            event.accept()
            return

        was_dragging = self._is_dragging
        self._drag_offset = None
        self._is_dragging = False
        self._click_start_pos = None

        if was_dragging:
            event.accept()
            return

        if self._current_action == "sleep":
            self._wake_from_sleep()
            event.accept()
            return

        if self._waking_from_sleep:
            event.accept()
            return

        self._click_count += 1
        # 每次点击都重置窗口计时器（滚动窗口，给用户更充裕的三击时间）
        self._click_reset_timer.start(config.LIE_BACK_CLICK_WINDOW)

        # 三击立即触发平躺撒娇，不等窗口到期
        if self._click_count >= 3:
            self._click_reset_timer.stop()
            count = self._click_count
            self._click_count = 0
            logger.info(f"三击（{count}次）→ lie_back 撒娇")
            self.play_action("lie_back", force=True)
            self._increase_intimacy(1)

        import time
        self._last_interaction_time = time.time()
        event.accept()

    def contextMenuEvent(self, event):
        """右键菜单"""
        menu = QMenu(self)
        # macOS 原生菜单会忽略 QSS border-radius，需设置半透明背景 + 无原生边框
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
        menu.setWindowFlags(menu.windowFlags() | Qt.NoDropShadowWindowHint)
        # 统一马卡龙毛玻璃风格：浅粉半透底色、28px大圆角、软圆字体、选中粉色
        menu.setFont(QFont(config.GLASS_FONT_FAMILY, 10))
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(255, 228, 235, 235);
                border: 1px solid rgba(255, 255, 255, 200);
                padding: 8px;
                font-family: "PingFang SC", "Microsoft YaHei";
            }
            QMenu::item {
                padding: 7px 26px;
                color: %s;
            }
            QMenu::item:selected {
                background-color: rgba(255, 182, 193, 220);
                color: #4A4A4A;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255, 182, 193, 120);
                margin: 4px 12px;
            }
        """ % config.GLASS_TEXT_COLOR)
        act_chat = QAction("AI 对话", self)
        act_chat.triggered.connect(self.open_chat)

        # —— 专注模式（原有）——
        act_exit_focus = QAction("手动结束专注模式", self)
        act_exit_focus.setEnabled(self._focus_mode or self._dnd_mode)
        act_exit_focus.triggered.connect(self._manual_exit_focus)

        act_focus = QAction("轻度专注", self)
        act_focus.setCheckable(True)
        act_focus.setChecked(self._focus_mode)
        act_focus.triggered.connect(lambda: self.set_focus_mode(not self._focus_mode))

        act_dnd = QAction("深度专注", self)
        act_dnd.setCheckable(True)
        act_dnd.setChecked(self._dnd_mode)
        act_dnd.triggered.connect(lambda: self.set_dnd_mode(not self._dnd_mode))

        # —— 办公工具分区（新增）——
        act_todo = QAction("打开待办清单", self)
        act_todo.triggered.connect(self._open_todo)

        act_calc = QAction("打开计算器", self)
        act_calc.triggered.connect(self._open_calculator)

        act_notes = QAction("打开随笔记事本", self)
        act_notes.triggered.connect(self._open_notes)

        act_shortcuts = QAction("电脑快捷操作面板", self)
        act_shortcuts.triggered.connect(self._open_shortcuts)

        # —— 健康提醒分区 ——
        # 喝水/久坐提醒界面统一，合并为「健康提醒设置」单一入口（面板内含总开关+喝水间隔+久坐间隔）
        act_reminder_set = QAction("健康提醒设置", self)
        act_reminder_set.triggered.connect(self._open_reminder_settings)

        # 快捷打卡动作：喝水打卡（手动打卡计入今日饮水次数）
        act_water = QAction("喝水打卡", self)
        act_water.triggered.connect(self._water_checkin)
        # 久坐打卡已移除：久坐改为用户设定时间到达后猫咪强制提醒

        # —— 原有基础功能 ——
        act_rename = QAction("设置宠物姓名", self)
        act_rename.triggered.connect(self._set_pet_name)

        act_help = QAction("交互说明", self)
        act_help.triggered.connect(self._show_interaction_help)

        # 组装菜单（分区层级）
        menu.addAction(act_chat)
        menu.addSeparator()
        menu.addAction(act_exit_focus)
        menu.addAction(act_focus)
        menu.addAction(act_dnd)
        menu.addSeparator()
        menu.addAction(act_todo)
        menu.addAction(act_calc)
        menu.addAction(act_notes)
        menu.addAction(act_shortcuts)
        menu.addSeparator()
        menu.addAction(act_reminder_set)
        menu.addAction(act_water)
        menu.addSeparator()
        menu.addAction(act_rename)
        menu.addAction(act_help)
        menu.addSeparator()
        act_quit = QAction("退出程序", self)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(act_quit)

        menu.exec_(event.globalPos())

    def _show_interaction_help(self):
        """显示交互说明对话框"""
        msg = QMessageBox(self)
        msg.setWindowTitle("交互说明")
        msg.setIcon(QMessageBox.Information)
        help_text = (
            "【鼠标交互】\n"
            "  • 单击猫咪 → 眨眼\n"
            "  • 双击猫咪 → 打开 AI 对话\n"
            "  • 三击猫咪 → 平躺撒娇\n"
            "  • 拖拽猫咪 → 移动位置\n"
            "  • 右键猫咪 → 打开菜单\n\n"
            "【菜单功能】\n"
            "  • 喝水打卡 → 猫咪喝水动画\n"
            "  • 休息打卡 → 猫咪伸懒腰\n"
            "  • 轻度专注 → 侧躺陪伴\n"
            "  • 深度专注 → 熟睡（屏蔽所有交互）\n"
            "  • 退出专注 → 伸懒腰 + 专属气泡 + 丝滑过渡\n\n"
            "【自动行为】\n"
            "  • 无操作时 → idle 视频循环播放\n"
            "  • 5 分钟无操作 → 进入睡眠\n"
            "  • 久坐提醒 → 伸懒腰动画\n"
            "  • 喝水提醒 → 喝水动画\n"
            "  • 长时间未对话 → 侧躺等待"
        )
        msg.setText(help_text)
        msg.exec_()

    # ========== 退出 ==========

    def quit_app(self):
        """退出应用"""
        self._save_config()
        if self._media_player:
            self._media_player.stop()
        self._stop_gif()
        self._idle_timer.stop()
        self._sleep_timer.stop()
        self._no_chat_timer.stop()
        self._auto_downgrade_timer.stop()
        self._click_reset_timer.stop()
        self._frame_watchdog.stop()
        if self._reminder_system:
            self._reminder_system.stop()
        self._bubble.hide()
        self._bubble.close()
        # 关闭毛玻璃举牌弹窗与环形进度条
        for dlg in list(self._glass_dialogs.values()):
            try:
                dlg.close()
            except Exception:
                pass
        self._glass_dialogs.clear()
        if self._ring_widget:
            try:
                self._ring_widget.close()
            except Exception:
                pass
        if self._chat_window:
            self._chat_window.close()
        if self._tools_panel:
            self._tools_panel.close()
        QApplication.instance().quit()
        sys.exit(0)
