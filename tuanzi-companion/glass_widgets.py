"""
桌面宠物 - 举牌式毛玻璃悬浮弹窗模块

提供一组低饱和马卡龙毛玻璃风格的顶层悬浮弹窗：
- GlassDialog：毛玻璃举牌弹窗基类（无边框/置顶/半透/淡入淡出/弹簧弹出/跟随猫咪/外部点击关闭）
- TodoGlassDialog：待办清单
- CalculatorGlassDialog：计算器（支持键盘输入）
- NotesGlassDialog：随笔记事本（自动保存）
- ShortcutGlassDialog：Mac 快捷键面板
- ReminderSettingGlassDialog：健康提醒设置
- ReminderActionGlassDialog：提醒触发举牌面板

视觉规范：28px 大圆角、浅粉/奶蓝半透底色、软圆字体、弹簧弹出缓动、统一 0.15s 淡入淡出。
所有弹窗均为 macOS 友好的顶层悬浮窗口，不被桌面软件遮挡。
"""

import os
import json
from datetime import datetime

from PyQt5.QtCore import (
    Qt, QTimer, QRect, QPoint, QEvent, pyqtSignal,
    QPropertyAnimation, QEasingCurve,
)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QTextEdit, QLabel,
    QCheckBox, QSlider, QGraphicsDropShadowEffect, QApplication,
)

import config

# 确保数据目录存在（与 tools_panel 一致）
try:
    os.makedirs(config.DATA_DIR, exist_ok=True)
except OSError:
    pass

# 计算器表达式临时缓存
CALC_CACHE_FILE = os.path.join(config.DATA_DIR, "calc_cache.txt")


# ==================== 子控件统一样式 ====================
_GLASS_TEXT = config.GLASS_TEXT_COLOR
_GLASS_FONT = config.GLASS_FONT_FAMILY

GLASS_CHILD_QSS = """
QLineEdit, QTextEdit, QListWidget {
    background: rgba(255, 255, 255, 160);
    border: 1px solid rgba(255, 255, 255, 180);
    border-radius: 12px;
    padding: 6px 8px;
    color: %s;
    selection-background-color: rgba(255, 182, 193, 180);
}
QLineEdit:focus, QTextEdit:focus, QListWidget:focus {
    border: 1px solid rgba(255, 182, 193, 220);
}
QPushButton {
    background: rgba(255, 255, 255, 180);
    color: %s;
    border: 1px solid rgba(255, 255, 255, 200);
    border-radius: 12px;
    padding: 6px 14px;
}
QPushButton:hover { background: rgba(255, 255, 255, 220); }
QPushButton:pressed { background: rgba(255, 182, 193, 160); }
QPushButton#danger { background: rgba(245, 108, 108, 180); color: #ffffff; }
QPushButton#danger:hover { background: rgba(247, 137, 137, 220); }
QPushButton#eq {
    background: %s;
    color: #ffffff;
    font-weight: bold;
}
QPushButton#eq:hover { background: rgba(255, 200, 215, 230); }
QLabel { background: transparent; color: %s; }
QCheckBox { background: transparent; color: %s; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 6px; }
QListWidget#todoList::item { padding: 4px 6px; }
""" % (_GLASS_TEXT, _GLASS_TEXT, config.GLASS_PINK_BG, _GLASS_TEXT, _GLASS_TEXT)


def _glass_font(point_size=11, bold=False):
    """生成毛玻璃软圆字体"""
    f = QFont(_GLASS_FONT, point_size)
    f.setBold(bold)
    return f


# ==================== 毛玻璃举牌弹窗基类 ====================
class GlassDialog(QWidget):
    """毛玻璃举牌弹窗基类：无边框/置顶/半透/淡入淡出/弹簧弹出/跟随猫咪/外部点击关闭"""

    closed = pyqtSignal()

    def __init__(self, parent_window=None, bg_color=None, fixed_size=(380, 460)):
        super().__init__(parent_window)
        self._bg_color = bg_color or config.GLASS_PINK_BG
        self._fixed_size = fixed_size
        self._pet_window = None
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(50)
        self._follow_timer.timeout.connect(self._follow_pet)
        self._fading_out = False
        self._container_margin = 10  # 给阴影留出的边距

        # 拖拽 / 缩放状态
        self._dragging = False
        self._drag_offset = QPoint()
        self._resizing = False
        self._resize_start_geom = QRect()
        self._resize_start_pos = QPoint()
        self._user_moved = False  # 用户拖拽/缩放后停止跟随猫咪

        # 无边框 + 置顶 + Tool + 半透明背景，适配 macOS
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # 允许放大缩小：设置最小/最大尺寸而非固定尺寸
        self.setMinimumSize(fixed_size[0] // 2, fixed_size[1] // 2)
        self.setMaximumSize(fixed_size[0] * 2, fixed_size[1] * 2)
        self.resize(*fixed_size)

        # 毛玻璃容器（带圆角与柔和阴影）
        self.glass_container = QWidget(self)
        self.glass_container.setObjectName("glassContainer")
        self._container_rect = QRect(
            self._container_margin,
            self._container_margin,
            self.width() - self._container_margin * 2,
            self.height() - self._container_margin * 2,
        )
        self.glass_container.setGeometry(self._container_rect)
        self.glass_container.setStyleSheet(
            """
            QWidget#glassContainer {
                background-color: %s;
                border-radius: %dpx;
                border: 1px solid rgba(255, 255, 255, 140);
            }
            """ % (self._bg_color, config.GLASS_RADIUS)
        )

        # 柔和外阴影
        try:
            shadow = QGraphicsDropShadowEffect(self.glass_container)
            shadow.setBlurRadius(24)
            shadow.setColor(QColor(0, 0, 0, 70))
            shadow.setOffset(0, 3)
            self.glass_container.setGraphicsEffect(shadow)
        except Exception:
            pass

        # 子控件统一样式
        self.glass_container.setStyleSheet(
            self.glass_container.styleSheet() + GLASS_CHILD_QSS
        )

        # 关闭按钮（右上角，退出弹窗）
        self.close_btn = QPushButton("×", self)
        self.close_btn.setObjectName("glassCloseBtn")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.fade_out)
        self.close_btn.setStyleSheet(
            """
            QPushButton#glassCloseBtn {
                background: rgba(255, 255, 255, 120);
                color: %s;
                border: none;
                border-radius: 11px;
                font-size: 14pt;
                font-weight: bold;
            }
            QPushButton#glassCloseBtn:hover { background: rgba(255, 182, 193, 200); }
            """ % _GLASS_TEXT
        )

        # 淡入淡出动画（作用于 windowOpacity）
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.setWindowOpacity(0.0)

        # 弹簧弹出动画（作用于容器 geometry，0.85 -> 1.0）
        self._spring_anim = QPropertyAnimation(self.glass_container, b"geometry", self)
        self._spring_anim.setEasingCurve(QEasingCurve.OutBack)

        # 安装全局点击外部关闭检测
        self._apply_global_click_to_close()

    def resizeEvent(self, event):
        """窗口缩放时同步容器与关闭按钮位置"""
        try:
            self._container_rect = QRect(
                self._container_margin,
                self._container_margin,
                self.width() - self._container_margin * 2,
                self.height() - self._container_margin * 2,
            )
            self.glass_container.setGeometry(self._container_rect)
            # 关闭按钮固定在容器右上角
            self.close_btn.move(
                self.width() - self.close_btn.width() - self._container_margin - 6,
                self._container_margin + 6,
            )
        except Exception:
            pass
        super().resizeEvent(event)

    # ---------- 拖拽 / 缩放 ----------
    def mousePressEvent(self, event):
        """左键按下：标题栏区域拖拽，右下角区域缩放"""
        if event.button() != Qt.LeftButton:
            return
        pos = event.pos()
        # 右下角 16px 区域 → 缩放
        if (self.width() - pos.x() <= 18) and (self.height() - pos.y() <= 18):
            self._resizing = True
            self._resize_start_geom = self.geometry()
            self._resize_start_pos = event.globalPos()
            self._user_moved = True
            self._stop_follow()
            event.accept()
            return
        # 顶部 36px 区域 → 拖拽（避免误触内容）
        if pos.y() <= 36:
            self._dragging = True
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            self._user_moved = True
            self._stop_follow()
            event.accept()

    def mouseMoveEvent(self, event):
        """拖拽中 / 缩放中"""
        if self._dragging and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPos() - self._drag_offset)
            event.accept()
        elif self._resizing and (event.buttons() & Qt.LeftButton):
            delta = event.globalPos() - self._resize_start_pos
            new_w = max(self.minimumWidth(), self._resize_start_geom.width() + delta.x())
            new_h = max(self.minimumHeight(), self._resize_start_geom.height() + delta.y())
            new_w = min(new_w, self.maximumWidth())
            new_h = min(new_h, self.maximumHeight())
            self.resize(new_w, new_h)
            event.accept()

    def mouseReleaseEvent(self, event):
        """释放鼠标：结束拖拽/缩放"""
        self._dragging = False
        self._resizing = False
        event.accept()

    def _follow_pet(self):
        """计算猫咪头部右上方位置并移动自身（用户已手动拖拽/缩放后不再跟随）"""
        if self._user_moved:
            return
        pet = self._pet_window
        if pet is None:
            return
        try:
            pet_x = pet.x()
            pet_y = pet.y()
            pet_w = pet.width()
            pet_h = pet.height()
        except Exception:
            return

        # 默认放在猫咪上方（头部右上方）
        x = pet_x + pet_w // 2 - 30
        y = pet_y - self.height() - 20
        # 超出屏幕顶部则放到猫咪下方
        if y < 0:
            y = pet_y + pet_h + 10

        # 水平方向避免溢出屏幕
        screen = QApplication.primaryScreen()
        if screen is not None:
            sg = screen.availableGeometry()
            if x + self.width() > sg.right():
                x = sg.right() - self.width()
            if x < sg.left():
                x = sg.left()
            if y + self.height() > sg.bottom():
                y = sg.bottom() - self.height()
            if y < sg.top():
                y = sg.top()
        self.move(x, y)

    # ---------- 容器布局 ----------
    def set_container_layout(self, layout):
        """把业务布局放进毛玻璃容器"""
        self.glass_container.setLayout(layout)

    # ---------- 跟随猫咪 ----------
    def attach_to_pet(self, pet_window):
        """绑定宠物窗口，启动跟随定时器"""
        self._pet_window = pet_window
        self._follow_pet()
        self._follow_timer.start()

    def _stop_follow(self):
        """停止跟随"""
        self._follow_timer.stop()

    # ---------- 淡入淡出 + 弹簧 ----------
    def fade_in(self):
        """显示弹窗：淡入 + 弹簧弹出"""
        if self._fading_out:
            return
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        # 立即定位到猫咪附近
        self._follow_pet()

        try:
            self._fade_anim.stop()
            try:
                self._fade_anim.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._fade_anim.setDuration(config.GLASS_FADE_MS)
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
            self._fade_anim.start()
        except Exception:
            self.setWindowOpacity(1.0)

        self._animate_spring_in()

    def _animate_spring_in(self):
        """弹簧弹出：容器从 0.85 缩放到 1.0"""
        try:
            full = QRect(self._container_rect)
            cx = full.center().x()
            cy = full.center().y()
            w = int(full.width() * 0.85)
            h = int(full.height() * 0.85)
            start = QRect(cx - w // 2, cy - h // 2, w, h)
            self._spring_anim.stop()
            self._spring_anim.setDuration(config.GLASS_SPRING_MS)
            self._spring_anim.setStartValue(start)
            self._spring_anim.setEndValue(full)
            self._spring_anim.setEasingCurve(QEasingCurve.OutBack)
            self._spring_anim.start()
        except Exception:
            self.glass_container.setGeometry(self._container_rect)

    def fade_out(self):
        """淡出 -> 隐藏 -> 发送 closed 信号"""
        if self._fading_out:
            return
        self._fading_out = True
        self._stop_follow()
        try:
            self._fade_anim.stop()
            try:
                self._fade_anim.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._fade_anim.finished.connect(self._on_fade_out_done)
            self._fade_anim.setDuration(config.GLASS_FADE_MS)
            self._fade_anim.setStartValue(self.windowOpacity())
            self._fade_anim.setEndValue(0.0)
            self._fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
            self._fade_anim.start()
        except Exception:
            self._on_fade_out_done()

    def _on_fade_out_done(self):
        """淡出完成"""
        try:
            self._fade_anim.finished.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.hide()
        self._fading_out = False
        self.closed.emit()

    # ---------- 外部点击关闭 ----------
    def _apply_global_click_to_close(self):
        """安装 QApplication 事件过滤器，检测弹窗外部点击"""
        try:
            QApplication.instance().installEventFilter(self)
        except Exception:
            pass

    def eventFilter(self, obj, event):
        """检测鼠标点击弹窗外部区域 -> 淡出关闭"""
        try:
            if event.type() == QEvent.MouseButtonPress:
                if self.isVisible() and not self._fading_out:
                    gp = event.globalPos()
                    if not self.geometry().contains(gp):
                        self.fade_out()
        except Exception:
            pass
        return False

    def keyPressEvent(self, event):
        """ESC 关闭弹窗"""
        if event.key() == Qt.Key_Escape:
            self.fade_out()
        else:
            super().keyPressEvent(event)


# ==================== 待办清单 ====================
class TodoGlassDialog(GlassDialog):
    """待办清单毛玻璃弹窗（复用 tools_panel.TodoTab 持久化逻辑）"""

    def __init__(self, parent_window=None):
        super().__init__(
            parent_window=parent_window,
            bg_color=config.GLASS_PINK_BG,
            fixed_size=(360, 420),
        )
        self._todos = []  # [{"text": str, "done": bool}, ...]
        self._init_ui()
        self._load_todos()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel("待办清单")
        title.setFont(_glass_font(13, bold=True))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 顶部输入区
        top = QHBoxLayout()
        top.setSpacing(6)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("输入待办后按回车添加…")
        self.input_edit.returnPressed.connect(self._add_todo)
        top.addWidget(self.input_edit, 1)
        self.add_btn = QPushButton("添加")
        self.add_btn.setFixedWidth(56)
        self.add_btn.clicked.connect(self._add_todo)
        top.addWidget(self.add_btn)
        layout.addLayout(top)

        # 待办列表
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("todoList")
        self.list_widget.itemChanged.connect(self._toggle_done)
        self.list_widget.itemDoubleClicked.connect(self._delete_item)
        layout.addWidget(self.list_widget, 1)

        # 底部进度 + 清空已完成
        bottom = QHBoxLayout()
        self.progress_label = QLabel("今日完成 0/0")
        self.progress_label.setStyleSheet("color: %s;" % _GLASS_TEXT)
        bottom.addWidget(self.progress_label)
        bottom.addStretch(1)
        self.clear_done_btn = QPushButton("清空已完成")
        self.clear_done_btn.setObjectName("danger")
        self.clear_done_btn.clicked.connect(self._delete_done)
        bottom.addWidget(self.clear_done_btn)
        layout.addLayout(bottom)

        self.set_container_layout(layout)

    # ----- 数据操作 -----
    def _add_todo(self):
        text = self.input_edit.text().strip()
        if not text:
            return
        self._todos.append({"text": text, "done": False})
        self.input_edit.clear()
        self._refresh_list()
        self._save_todos()
        self._update_progress()

    def _toggle_done(self, item):
        row = self.list_widget.row(item)
        if 0 <= row < len(self._todos):
            self._todos[row]["done"] = (item.checkState() == Qt.Checked)
            self._refresh_list(row)
            self._save_todos()
            self._update_progress()

    def _delete_item(self, item):
        """双击删除单条"""
        row = self.list_widget.row(item)
        if 0 <= row < len(self._todos):
            del self._todos[row]
            self._refresh_list()
            self._save_todos()
            self._update_progress()

    def _delete_done(self):
        self._todos = [t for t in self._todos if not t["done"]]
        self._refresh_list()
        self._save_todos()
        self._update_progress()

    # ----- 列表刷新 -----
    def _refresh_list(self, keep_row=None):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for todo in self._todos:
            item = QListWidgetItem(todo["text"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if todo["done"] else Qt.Unchecked)
            if todo["done"]:
                font = item.font()
                font.setStrikeOut(True)
                item.setFont(font)
                item.setForeground(Qt.gray)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        if keep_row is not None and 0 <= keep_row < self.list_widget.count():
            self.list_widget.setCurrentRow(keep_row)

    def _update_progress(self):
        total = len(self._todos)
        done = sum(1 for t in self._todos if t["done"])
        self.progress_label.setText("今日完成 %d/%d" % (done, total))

    # ----- 持久化 -----
    def _load_todos(self):
        if os.path.exists(config.TODO_FILE):
            try:
                with open(config.TODO_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._todos = [
                        t for t in data
                        if isinstance(t, dict) and "text" in t and "done" in t
                    ]
            except (json.JSONDecodeError, OSError):
                self._todos = []
        self._refresh_list()
        self._update_progress()

    def _save_todos(self):
        try:
            with open(config.TODO_FILE, "w", encoding="utf-8") as f:
                json.dump(self._todos, f, ensure_ascii=False, indent=2)
        except OSError:
            pass


# ==================== 计算器 ====================
class CalculatorGlassDialog(GlassDialog):
    """计算器毛玻璃弹窗（支持鼠标 + 键盘输入）"""

    calc_done = pyqtSignal(str)  # 计算完成，参数为结果文案/结果

    def __init__(self, parent_window=None):
        super().__init__(
            parent_window=parent_window,
            bg_color=config.GLASS_PINK_BG,
            fixed_size=(280, 380),
        )
        self._current = "0"
        self._stored = None
        self._operator = None
        self._reset_display = False
        self._init_ui()
        self._load_cache()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # 顶部只读显示屏（右对齐大字号，18px 圆角匹配毛玻璃风格）
        self.display = QLineEdit("0")
        self.display.setReadOnly(True)
        self.display.setAlignment(Qt.AlignRight)
        self.display.setFocusPolicy(Qt.NoFocus)
        self.display.setStyleSheet(
            "QLineEdit { font-size: 22px; padding: 10px; "
            "background: rgba(255,255,255,200); border-radius: 18px; "
            "color: %s; }" % _GLASS_TEXT
        )
        layout.addWidget(self.display)

        # 4 列按钮网格
        grid = QGridLayout()
        grid.setSpacing(6)
        # (label, token, row, col, rowSpan, colSpan)
        buttons = [
            ("C", "C", 0, 0, 1, 1),
            ("⌫", "backspace", 0, 1, 1, 1),
            ("÷", "/", 0, 2, 1, 1),
            ("×", "*", 0, 3, 1, 1),
            ("7", "7", 1, 0, 1, 1),
            ("8", "8", 1, 1, 1, 1),
            ("9", "9", 1, 2, 1, 1),
            ("−", "-", 1, 3, 1, 1),
            ("4", "4", 2, 0, 1, 1),
            ("5", "5", 2, 1, 1, 1),
            ("6", "6", 2, 2, 1, 1),
            ("+", "+", 2, 3, 1, 1),
            ("1", "1", 3, 0, 1, 1),
            ("2", "2", 3, 1, 1, 1),
            ("3", "3", 3, 2, 1, 1),
            ("=", "=", 3, 3, 2, 1),
            ("0", "0", 4, 0, 1, 2),
            (".", ".", 4, 2, 1, 1),
        ]
        for label, token, row, col, rs, cs in buttons:
            btn = QPushButton(label)
            btn.setFont(_glass_font(14, bold=True))
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(36)
            if token == "=":
                btn.setObjectName("eq")
            elif token == "C":
                btn.setObjectName("danger")
            btn.clicked.connect(lambda _, t=token: self._on_token(t))
            grid.addWidget(btn, row, col, rs, cs)

        layout.addLayout(grid, 1)
        self.set_container_layout(layout)

    # ----- 计算逻辑（移植自 tools_panel.CalculatorTab）-----
    def _on_token(self, token):
        if token == "backspace":
            self._backspace()
        elif token in "0123456789":
            self._input_digit(token)
        elif token == ".":
            self._input_dot()
        elif token in "+-*/":
            self._input_operator(token)
        elif token == "=":
            self._calculate_and_emit()
        elif token == "C":
            self._clear()
        self._update_display()

    def _on_button_clicked(self, text):
        """兼容旧入口：把符号映射回内部 token"""
        mapping = {"÷": "/", "×": "*", "−": "-", "⌫": "backspace"}
        self._on_token(mapping.get(text, text))

    def _input_digit(self, digit):
        if self._reset_display or self._current == "0":
            self._current = digit
            self._reset_display = False
        else:
            self._current += digit

    def _input_dot(self):
        if self._reset_display:
            self._current = "0"
            self._reset_display = False
        if "." not in self._current:
            self._current += "."

    def _input_operator(self, op):
        if (
            self._operator is not None
            and self._stored is not None
            and not self._reset_display
        ):
            self._calculate()
        try:
            self._stored = float(self._current)
        except ValueError:
            self._stored = 0.0
        self._operator = op
        self._reset_display = True

    def _calculate(self):
        if self._operator is None or self._stored is None:
            return
        try:
            current = float(self._current)
        except ValueError:
            current = 0.0
        op = self._operator
        if op == "+":
            result = self._stored + current
        elif op == "-":
            result = self._stored - current
        elif op == "*":
            result = self._stored * current
        elif op == "/":
            if current == 0:
                self._current = "Error"
                self._stored = None
                self._operator = None
                self._reset_display = True
                return
            result = self._stored / current
        else:
            return
        # 整数则去掉小数点
        if isinstance(result, float) and result.is_integer():
            self._current = str(int(result))
        else:
            self._current = str(round(result, 10))
        self._stored = float(self._current)
        self._operator = None
        self._reset_display = True

    def _calculate_and_emit(self):
        """按等号计算并发送 calc_done 信号"""
        self._calculate()
        self.calc_done.emit(self._current)

    def _backspace(self):
        if self._current in ("0", "Error", ""):
            self._current = "0"
            return
        self._current = self._current[:-1]
        if self._current in ("", "-"):
            self._current = "0"

    def _clear(self):
        self._current = "0"
        self._stored = None
        self._operator = None
        self._reset_display = False

    def _update_display(self):
        self.display.setText(self._current)

    # ----- 键盘输入 -----
    def keyPressEvent(self, event):
        key = event.key()
        text = event.text()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._calculate_and_emit()
            self._update_display()
            return
        if key == Qt.Key_Escape:
            # 计算器内 ESC 清空（不关闭弹窗）
            self._clear()
            self._update_display()
            return
        if key == Qt.Key_Backspace:
            self._backspace()
            self._update_display()
            return
        if text and text in "0123456789.+-*/":
            self._on_token(text)
            return
        super().keyPressEvent(event)

    def fade_in(self):
        """显示并获取键盘焦点"""
        super().fade_in()
        try:
            self.activateWindow()
            self.raise_()
            self.setFocus(Qt.OtherFocusReason)
        except Exception:
            pass

    def fade_out(self):
        """关闭时保存当前表达式缓存"""
        self._save_cache()
        super().fade_out()

    # ----- 缓存 -----
    def _load_cache(self):
        try:
            if os.path.exists(CALC_CACHE_FILE):
                with open(CALC_CACHE_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    self._current = content
                    self._update_display()
        except OSError:
            pass

    def _save_cache(self):
        try:
            with open(CALC_CACHE_FILE, "w", encoding="utf-8") as f:
                f.write(self._current)
        except OSError:
            pass


# ==================== 随笔记事本 ====================
class NotesGlassDialog(GlassDialog):
    """随笔记事本毛玻璃弹窗（自动保存，复用 tools_panel.NotesTab 持久化逻辑）"""

    def __init__(self, parent_window=None):
        super().__init__(
            parent_window=parent_window,
            bg_color=config.GLASS_PINK_BG,
            fixed_size=(340, 360),
        )
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_notes)
        self._init_ui()
        self._load_notes()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel("随笔记事")
        title.setFont(_glass_font(13, bold=True))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 无边框文本区
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("随手记录灵感与想法…自动保存")
        self.text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text_edit, 1)

        # 上次保存时间
        self.status_label = QLabel("上次保存：尚未保存")
        self.status_label.setStyleSheet("color: rgba(110,110,110,180); font-size: 10px;")
        layout.addWidget(self.status_label)

        # 底部按钮
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.copy_btn = QPushButton("复制全部")
        self.copy_btn.clicked.connect(self._copy_all)
        bottom.addWidget(self.copy_btn)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.setObjectName("danger")
        self.clear_btn.clicked.connect(self._clear_text)
        bottom.addWidget(self.clear_btn)
        layout.addLayout(bottom)

        self.set_container_layout(layout)

    def _on_text_changed(self):
        """防抖保存：textChanged 触发 500ms 延时"""
        self._save_timer.start()

    def _copy_all(self):
        try:
            QApplication.clipboard().setText(self.text_edit.toPlainText())
        except Exception:
            pass

    def _clear_text(self):
        self.text_edit.clear()

    # ----- 持久化 -----
    def _load_notes(self):
        if os.path.exists(config.NOTES_FILE):
            try:
                with open(config.NOTES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    if "content" in data:
                        # blockSignals 避免触发自动保存
                        self.text_edit.blockSignals(True)
                        self.text_edit.setPlainText(data["content"])
                        self.text_edit.blockSignals(False)
                    if "saved_at" in data:
                        self._update_status(data["saved_at"])
            except (json.JSONDecodeError, OSError):
                pass

    def _save_notes(self):
        content = self.text_edit.toPlainText()
        saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = {"content": content, "saved_at": saved_at}
        try:
            with open(config.NOTES_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._update_status(saved_at)
        except OSError:
            pass

    def _update_status(self, saved_at):
        self.status_label.setText("上次保存：%s" % saved_at)

    def fade_out(self):
        """关闭前立即保存一次"""
        self._save_timer.stop()
        self._save_notes()
        super().fade_out()


# ==================== Mac 快捷键面板 ====================
class ShortcutGlassDialog(GlassDialog):
    """Mac 快捷键展示面板（纯展示）"""

    # 三组快捷键：(组标题, [(功能, 快捷键), ...])
    _GROUPS = [
        ("窗口管理", [
            ("分屏", "Ctrl + Cmd + F"),
            ("最小化", "Cmd + M"),
            ("切换应用", "Cmd + Tab"),
        ]),
        ("文本编辑", [
            ("复制", "Cmd + C"),
            ("粘贴", "Cmd + V"),
            ("撤销", "Cmd + Z"),
            ("全选", "Cmd + A"),
        ]),
        ("截图录屏", [
            ("区域截图", "Cmd + Shift + 4"),
            ("全屏截图", "Cmd + Shift + 3"),
            ("录屏", "Cmd + Shift + 5"),
        ]),
    ]

    def __init__(self, parent_window=None):
        super().__init__(
            parent_window=parent_window,
            bg_color=config.GLASS_PINK_BG,
            fixed_size=(340, 400),
        )
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Mac 快捷键")
        title.setFont(_glass_font(13, bold=True))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        for group_title, items in self._GROUPS:
            card = self._build_group_card(group_title, items)
            layout.addWidget(card)

        layout.addStretch(1)
        self.set_container_layout(layout)

    def _build_group_card(self, group_title, items):
        """构建单个分组卡片（浅色背景区分）"""
        card = QWidget()
        card.setObjectName("groupCard")
        # 用 objectName 限定，避免影响子 QLabel 背景
        card.setStyleSheet(
            "QWidget#groupCard { background: rgba(255, 255, 255, 120); "
            "border-radius: 14px; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(4)

        head = QLabel(group_title)
        head.setFont(_glass_font(11, bold=True))
        head.setStyleSheet("color: %s;" % _GLASS_TEXT)
        card_layout.addWidget(head)

        for name, keys in items:
            row = QHBoxLayout()
            name_label = QLabel(name)
            name_label.setStyleSheet("color: %s;" % _GLASS_TEXT)
            row.addWidget(name_label)
            row.addStretch(1)
            key_label = QLabel(keys)
            key_label.setStyleSheet(
                "color: #B84B66; background: rgba(255,255,255,180); "
                "border-radius: 6px; padding: 2px 8px;"
            )
            row.addWidget(key_label)
            card_layout.addLayout(row)

        return card


# ==================== 健康提醒设置 ====================
class ReminderSettingGlassDialog(GlassDialog):
    """健康提醒设置毛玻璃弹窗"""

    settings_changed = pyqtSignal(dict)  # {"enabled", "sit_minutes", "water_minutes"}

    def __init__(self, parent_window=None):
        super().__init__(
            parent_window=parent_window,
            bg_color=config.GLASS_PINK_BG,
            fixed_size=(340, 380),
        )
        state = self._load_reminder_state()
        self._enabled = state.get("enabled", config.HEALTH_REMINDER_ENABLED)
        self._sit_minutes = state.get("sit_minutes", config.SIT_REMINDER_INTERVAL)
        self._water_minutes = state.get("water_minutes", config.WATER_REMINDER_INTERVAL)
        self._water_count = state.get("water_count", 0)
        self._init_ui()
        self._sync_labels()

    @staticmethod
    def _load_reminder_state():
        """读取提醒状态文件，损坏则返回空 dict"""
        if os.path.exists(config.REMINDER_STATE_FILE):
            try:
                with open(config.REMINDER_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("健康提醒设置")
        title.setFont(_glass_font(13, bold=True))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 总开关
        self.enable_check = QCheckBox("健康提醒总开关")
        self.enable_check.setChecked(bool(self._enabled))
        layout.addWidget(self.enable_check)

        # 喝水间隔
        self.water_value_label = QLabel("")
        self.water_slider = self._build_interval_slider(
            layout, "喝水提醒间隔", self._water_minutes, self._on_water_changed
        )
        layout.addWidget(self.water_value_label)

        # 久坐间隔
        self.sit_value_label = QLabel("")
        self.sit_slider = self._build_interval_slider(
            layout, "久坐提醒间隔", self._sit_minutes, self._on_sit_changed
        )
        layout.addWidget(self.sit_value_label)

        # 今日饮水打卡次数
        self.water_count_label = QLabel("")
        self.water_count_label.setStyleSheet("color: %s;" % _GLASS_TEXT)
        layout.addWidget(self.water_count_label)

        layout.addStretch(1)
        self.set_container_layout(layout)

    def _build_interval_slider(self, parent_layout, name, init_value, on_change):
        """构建一组「标签 + 透明玻璃质感粉色滑块」
        拖动时实时更新标签（sliderMoved），释放时才触发业务回调（sliderReleased），
        避免 valueChanged 在拖动过程中频繁触发导致的卡顿不丝滑。
        """
        head = QHBoxLayout()
        name_label = QLabel(name)
        name_label.setStyleSheet("color: %s;" % _GLASS_TEXT)
        head.addWidget(name_label)
        head.addStretch(1)
        parent_layout.addLayout(head)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(config.HEALTH_REMINDER_MIN_MINUTES)
        slider.setMaximum(config.HEALTH_REMINDER_MAX_MINUTES)
        slider.setSingleStep(5)
        slider.setPageStep(10)
        slider.setValue(int(init_value))
        # 透明玻璃质感拉条 + 粉色滑块手柄
        slider.setStyleSheet(
            """
            QSlider {
                background: transparent;
                border: none;
                height: 22px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: rgba(255, 255, 255, 160);
                border: 1px solid rgba(255, 255, 255, 180);
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: rgba(255, 182, 193, 220);
                border-radius: 3px;
            }
            QSlider::add-page:horizontal {
                background: rgba(255, 255, 255, 100);
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: rgba(255, 255, 255, 240);
                border: 2px solid rgba(255, 182, 193, 220);
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: rgba(255, 240, 245, 255);
                border: 2px solid rgba(255, 150, 170, 240);
            }
            QSlider::handle:horizontal:pressed {
                background: rgba(255, 182, 193, 240);
            }
            """
        )
        # 拖动时实时同步数值标签（轻量，不触发业务回调）
        slider.sliderMoved.connect(on_change)
        # 释放时触发业务回调（持久化等重操作放这里，避免拖动中卡顿）
        slider.sliderReleased.connect(lambda: on_change(slider.value()))
        parent_layout.addWidget(slider)
        return slider

    def _on_water_changed(self, value):
        self._water_minutes = int(value)
        self._sync_labels()

    def _on_sit_changed(self, value):
        self._sit_minutes = int(value)
        self._sync_labels()

    def _sync_labels(self):
        self.water_value_label.setText("当前：%d 分钟" % self._water_minutes)
        self.sit_value_label.setText("当前：%d 分钟" % self._sit_minutes)
        self.water_count_label.setText("今日饮水打卡：%d 次" % self._water_count)

    def set_water_count(self, count):
        """主窗口传入当前饮水打卡次数"""
        self._water_count = int(count)
        self._sync_labels()

    def fade_out(self):
        """关闭时发送最新设置"""
        payload = {
            "enabled": bool(self.enable_check.isChecked()),
            "sit_minutes": int(self.sit_slider.value()),
            "water_minutes": int(self.water_slider.value()),
        }
        self.settings_changed.emit(payload)
        super().fade_out()


# ==================== 提醒触发举牌面板 ====================
class ReminderActionGlassDialog(GlassDialog):
    """提醒触发时的举牌面板（喝水/久坐）"""

    done_requested = pyqtSignal(str)    # 参数为提醒类型 "water"/"sit"
    snooze_requested = pyqtSignal(str)

    _EMOJI = {"water": "💧", "sit": "🐾"}
    _TITLE = {"water": "喝水提醒", "sit": "久坐提醒"}
    _DONE_TEXT = {"water": "已完成喝水", "sit": "已起身活动"}
    _SNOOZE_TEXT = {"water": "稍后提醒（延后 10 分钟）", "sit": "延后 15 分钟"}

    def __init__(self, reminder_type, message, parent_window=None):
        # 先算出毛玻璃底色再调用父类初始化（Qt 子类应优先 super().__init__）
        bg_color = config.GLASS_PINK_BG
        super().__init__(
            parent_window=parent_window,
            bg_color=bg_color,
            fixed_size=(320, 240),
        )
        self.reminder_type = reminder_type
        self.message = message
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(6)

        emoji = self._EMOJI.get(self.reminder_type, "🔔")
        title = self._TITLE.get(self.reminder_type, "提醒")

        self.icon_label = QLabel(emoji)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFont(_glass_font(28))
        layout.addWidget(self.icon_label)

        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setFont(_glass_font(13, bold=True))
        layout.addWidget(self.title_label)

        self.message_label = QLabel(self.message)
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setFont(_glass_font(10))
        layout.addWidget(self.message_label)

        layout.addStretch(1)

        # 两个按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        self.done_btn = QPushButton(self._DONE_TEXT.get(self.reminder_type, "完成"))
        self.done_btn.setCursor(Qt.PointingHandCursor)
        self.done_btn.clicked.connect(self._on_done)
        btn_layout.addWidget(self.done_btn)

        self.snooze_btn = QPushButton(self._SNOOZE_TEXT.get(self.reminder_type, "稍后提醒"))
        self.snooze_btn.setCursor(Qt.PointingHandCursor)
        self.snooze_btn.clicked.connect(self._on_snooze)
        btn_layout.addWidget(self.snooze_btn)
        layout.addLayout(btn_layout)

        self.set_container_layout(layout)

    def _on_done(self):
        self.done_requested.emit(self.reminder_type)
        self.fade_out()

    def _on_snooze(self):
        self.snooze_requested.emit(self.reminder_type)
        self.fade_out()


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)

    # 简单自测：展示计算器弹窗
    dlg = CalculatorGlassDialog()
    dlg.calc_done.connect(lambda r: print("calc_done:", r))
    dlg.fade_in()
    sys.exit(app.exec_())
