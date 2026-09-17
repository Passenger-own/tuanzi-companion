"""
桌面宠物 AI 对话模块
使用 DeepSeek API 实现智能对话功能

界面风格：低饱和马卡龙毛玻璃，28px 大圆角，浅粉/奶蓝半透底色，软圆字体，弹簧弹出缓动
与 glass_widgets 中的举牌弹窗保持视觉统一。
"""

import os
import json
import requests
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit, QPushButton,
    QLabel, QGraphicsDropShadowEffect, QApplication,
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QRect, QPoint, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QTextCursor, QColor, QFont

import config


class ChatWorker(QThread):
    """在独立线程中调用 DeepSeek API，避免阻塞 UI"""

    # 信号：API 调用成功时发送回复文本，失败时发送错误信息
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, messages):
        super().__init__()
        self.messages = messages

    def run(self):
        try:
            headers = {
                "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": config.DEEPSEEK_MODEL,
                "messages": self.messages,
                "stream": False,
            }
            resp = requests.post(
                config.DEEPSEEK_API_URL,
                headers=headers,
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
            self.finished.emit(reply)
        except requests.exceptions.Timeout:
            self.error.emit("请求超时了，请稍后再试～")
        except requests.exceptions.ConnectionError:
            self.error.emit("网络连接失败，请检查网络～")
        except requests.exceptions.HTTPError as e:
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except Exception:
                pass
            self.error.emit(f"API 调用失败：{e}\n{detail}" if detail else f"API 调用失败：{e}")
        except (KeyError, IndexError, ValueError):
            self.error.emit("解析 AI 回复失败，请稍后再试～")
        except Exception as e:
            self.error.emit(f"发生未知错误：{e}")


def _glass_font(point_size=11, bold=False):
    """生成毛玻璃软圆字体"""
    f = QFont(config.GLASS_FONT_FAMILY, point_size)
    f.setBold(bold)
    return f


# 子控件统一样式（与 glass_widgets.GLASS_CHILD_QSS 保持一致的马卡龙风格）
CHAT_CHILD_QSS = """
QTextEdit#chatDisplay {
    background: rgba(255, 255, 255, 180);
    border: 1px solid rgba(255, 255, 255, 180);
    border-radius: 18px;
    padding: 10px;
    color: %s;
    selection-background-color: rgba(255, 182, 193, 180);
}
QLineEdit#inputBox {
    background: rgba(255, 255, 255, 180);
    border: 1px solid rgba(255, 255, 255, 180);
    border-radius: 18px;
    padding: 8px 14px;
    color: %s;
}
QLineEdit#inputBox:focus {
    border: 1px solid rgba(255, 182, 193, 220);
}
QPushButton#sendButton {
    background: rgba(255, 182, 193, 220);
    color: #ffffff;
    border: none;
    border-radius: 16px;
    padding: 8px 20px;
    font-weight: bold;
}
QPushButton#sendButton:hover { background: rgba(255, 200, 215, 240); }
QPushButton#sendButton:pressed { background: rgba(255, 150, 175, 220); }
QPushButton#sendButton:disabled { background: rgba(200, 200, 200, 160); color: rgba(255,255,255,200); }
QPushButton#glassCloseBtn {
    background: rgba(255, 255, 255, 120);
    color: %s;
    border: none;
    border-radius: 14px;
    font-size: 14pt;
    font-weight: bold;
}
QPushButton#glassCloseBtn:hover { background: rgba(255, 182, 193, 200); }
QLabel { background: transparent; color: %s; }
""" % (config.GLASS_TEXT_COLOR, config.GLASS_TEXT_COLOR, config.GLASS_TEXT_COLOR, config.GLASS_TEXT_COLOR)


class ChatWindow(QWidget):
    """AI 聊天窗口（马卡龙毛玻璃风格，与其他举牌弹窗视觉统一）"""

    def __init__(self):
        super().__init__()
        # 对话历史（含 system prompt 设定宠物角色）
        self.messages = [
            {
                "role": "system",
                "content": (
                    f"你是一只可爱的桌面宠物，名字叫「{config.PET_NAME}」。"
                    "请用可爱、友好、俏皮的语气与主人对话，回复要简短生动，"
                    "适当使用颜文字或表情，让主人感到温暖和陪伴。"
                    "你是主人贴心的伙伴，关心主人的日常，会主动鼓励主人。"
                ),
            }
        ]
        # 当前正在进行的请求线程
        self.worker = None
        # 显示中的消息列表，元素为 (role, text)：role ∈ {"user", "assistant", "thinking"}
        # 用于在收到回复后精准移除「思考中...」占位消息
        self.displayed_messages = []
        # 弹簧/淡入动画
        self._fade_anim = None
        self._spring_anim = None
        self._container_margin = 12
        # 拖拽
        self._dragging = False
        self._drag_offset = QPoint()

        self._init_window()
        self._init_ui()
        self._init_style()
        self._connect_signals()

        # 加载持久化历史对话
        self._load_chat_history()

        # 欢迎语（仅首次打开时显示，有历史记录则不显示）
        if len(self.displayed_messages) == 0:
            self._add_message("assistant", f"主人好呀～我是 {config.PET_NAME}，有什么想聊的尽管说哦！(◕ᴗ◕✿)")

    # ---------- 窗口与样式 ----------

    def _init_window(self):
        """无边框 + 置顶 + Tool + 半透明背景（与 GlassDialog 一致）"""
        self.setWindowTitle(f"{config.PET_NAME} · AI 对话")
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(420, 540)

    def _init_ui(self):
        """初始化界面：毛玻璃容器 + 标题栏 + 聊天区 + 输入区"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            self._container_margin, self._container_margin,
            self._container_margin, self._container_margin,
        )
        outer.setSpacing(0)

        # 毛玻璃容器（28px 大圆角，浅粉半透底色）
        self.glass_container = QWidget(self)
        self.glass_container.setObjectName("glassContainer")
        self.glass_container.setGeometry(QRect(
            self._container_margin, self._container_margin,
            self.width() - self._container_margin * 2,
            self.height() - self._container_margin * 2,
        ))
        self.glass_container.setStyleSheet(
            """
            QWidget#glassContainer {
                background-color: %s;
                border-radius: %dpx;
                border: 1px solid rgba(255, 255, 255, 140);
            }
            """ % (config.GLASS_PINK_BG, config.GLASS_RADIUS)
        )

        # 柔和外阴影
        try:
            shadow = QGraphicsDropShadowEffect(self.glass_container)
            shadow.setBlurRadius(28)
            shadow.setColor(QColor(0, 0, 0, 70))
            shadow.setOffset(0, 3)
            self.glass_container.setGraphicsEffect(shadow)
        except Exception:
            pass

        container_layout = QVBoxLayout(self.glass_container)
        container_layout.setContentsMargins(16, 14, 16, 14)
        container_layout.setSpacing(10)

        # 标题栏（宠物名 + 关闭按钮，可拖拽）
        title_bar = QHBoxLayout()
        title_bar.setSpacing(8)
        self.title_label = QLabel(f"与 {config.PET_NAME} 聊天", self.glass_container)
        self.title_label.setObjectName("titleLabel")
        self.title_label.setFont(_glass_font(14, bold=True))
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title_bar.addWidget(self.title_label, 1)

        self.close_btn = QPushButton("×", self.glass_container)
        self.close_btn.setObjectName("glassCloseBtn")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.close)
        title_bar.addWidget(self.close_btn)
        container_layout.addLayout(title_bar)

        # 聊天记录显示区
        self.chat_display = QTextEdit(self.glass_container)
        self.chat_display.setReadOnly(True)
        self.chat_display.setObjectName("chatDisplay")
        self.chat_display.setFont(_glass_font(11))
        container_layout.addWidget(self.chat_display, 1)

        # 底部输入区
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)
        self.input_box = QLineEdit(self.glass_container)
        self.input_box.setObjectName("inputBox")
        self.input_box.setFont(_glass_font(11))
        self.input_box.setPlaceholderText("输入消息，按回车发送…")
        input_layout.addWidget(self.input_box, 1)

        self.send_button = QPushButton("发送", self.glass_container)
        self.send_button.setObjectName("sendButton")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setFont(_glass_font(11, bold=True))
        input_layout.addWidget(self.send_button)
        container_layout.addLayout(input_layout)

        outer.addWidget(self.glass_container)

    def _init_style(self):
        """应用子控件统一样式"""
        self.setStyleSheet(CHAT_CHILD_QSS)

    def _connect_signals(self):
        """连接信号与槽"""
        self.send_button.clicked.connect(self._on_send_clicked)
        self.input_box.returnPressed.connect(self._on_send_clicked)

    # ---------- 弹簧弹出 + 淡入 ----------

    def _container_rect(self):
        return QRect(
            self._container_margin, self._container_margin,
            self.width() - self._container_margin * 2,
            self.height() - self._container_margin * 2,
        )

    def showEvent(self, event):
        """每次显示时：淡入 + 弹簧弹出"""
        super().showEvent(event)
        try:
            # 淡入（作用于 windowOpacity）
            self.setWindowOpacity(0.0)
            self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
            self._fade_anim.setDuration(config.GLASS_FADE_MS)
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
            self._fade_anim.start()

            # 弹簧弹出（容器从 0.85 缩放到 1.0）
            full = self._container_rect()
            cx = full.center().x()
            cy = full.center().y()
            w = int(full.width() * 0.85)
            h = int(full.height() * 0.85)
            start = QRect(cx - w // 2, cy - h // 2, w, h)
            self._spring_anim = QPropertyAnimation(self.glass_container, b"geometry", self)
            self._spring_anim.setDuration(config.GLASS_SPRING_MS)
            self._spring_anim.setStartValue(start)
            self._spring_anim.setEndValue(full)
            self._spring_anim.setEasingCurve(QEasingCurve.OutBack)
            self._spring_anim.start()
        except Exception:
            self.glass_container.setGeometry(self._container_rect())
            self.setWindowOpacity(1.0)

    def resizeEvent(self, event):
        """缩放时同步容器"""
        try:
            self.glass_container.setGeometry(self._container_rect())
        except Exception:
            pass
        super().resizeEvent(event)

    # ---------- 拖拽 ----------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPos() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()

    # ---------- 消息显示 ----------

    @staticmethod
    def _escape_html(text):
        """转义 HTML 特殊字符，防止富文本解析问题"""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _build_bubble_html(self, role, text):
        """根据角色构建气泡 HTML

        role="user":       靠右，浅粉气泡
        role="assistant":  靠左，奶白气泡
        role="thinking":   靠左，奶白气泡（斜体，弱化）
        """
        safe = self._escape_html(text)
        if role == "user":
            return (
                '<div style="text-align:right; margin:6px 0;">'
                f'<span style="display:inline-block; background-color:rgba(255,182,193,230); '
                'color:#ffffff; padding:8px 12px; border-radius:14px; '
                f'max-width:280px;">{safe}</span>'
                '</div>'
            )
        # assistant / thinking 共用奶白气泡，思考中加斜体弱化
        italic = "font-style:italic; color:#8a94a6;" if role == "thinking" else ""
        return (
            '<div style="text-align:left; margin:6px 0;">'
            f'<span style="display:inline-block; background-color:rgba(255,255,255,210); '
            f'color:#6E6E6E; padding:8px 12px; border-radius:14px; '
            f'max-width:280px; {italic}">{safe}</span>'
            '</div>'
        )

    def _add_message(self, role, text):
        """追加一条消息到显示区并记录到 displayed_messages"""
        self.displayed_messages.append((role, text))
        self._render_message(self._build_bubble_html(role, text))

    def _render_message(self, html):
        """向聊天显示区追加 HTML 内容并滚动到底部"""
        self.chat_display.moveCursor(QTextCursor.End)
        self.chat_display.insertHtml(html)
        self.chat_display.append("")  # 增加空行间隔
        self.chat_display.moveCursor(QTextCursor.End)

    def _remove_last_thinking(self):
        """移除最后一条「思考中...」占位消息并重渲染整个聊天区"""
        # 倒序移除最后一条 thinking
        for i in range(len(self.displayed_messages) - 1, -1, -1):
            if self.displayed_messages[i][0] == "thinking":
                del self.displayed_messages[i]
                break
        self._rerender_all()

    def _rerender_all(self):
        """根据 displayed_messages 重新渲染整个聊天显示区"""
        self.chat_display.clear()
        for role, text in self.displayed_messages:
            self._render_message(self._build_bubble_html(role, text))

    # ---------- 发送逻辑 ----------

    def _on_send_clicked(self):
        """发送按钮 / 回车 触发"""
        # 若正在请求中，忽略新输入
        if self.worker is not None and self.worker.isRunning():
            return

        text = self.input_box.text().strip()
        if not text:
            return

        # 检查 API Key
        if not getattr(config, "DEEPSEEK_API_KEY", ""):
            self._add_message("assistant", "请先配置 DeepSeek API Key：\n方式一：在 config.py 中填写 DEEPSEEK_API_KEY\n方式二：设置环境变量 DEEPSEEK_API_KEY")
            return

        # 显示用户消息
        self._add_message("user", text)
        self.input_box.clear()

        # 记录到对话历史（用于 API）
        self.messages.append({"role": "user", "content": text})
        self._save_chat_history()

        # 显示思考中提示
        self._add_message("thinking", "思考中...")
        self._set_thinking(True)

        # 启动工作线程
        self.worker = ChatWorker(self.messages)
        self.worker.finished.connect(self._on_reply)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_reply(self, reply):
        """收到 AI 回复"""
        self._remove_last_thinking()
        self._add_message("assistant", reply)
        self.messages.append({"role": "assistant", "content": reply})
        self._save_chat_history()
        self._set_thinking(False)

    def _on_error(self, err_msg):
        """API 出错"""
        self._remove_last_thinking()
        self._add_message("assistant", f"出错了：{err_msg}")
        self._set_thinking(False)

    # ---------- 历史对话持久化 ----------

    def _load_chat_history(self):
        """从文件加载历史对话记录（重启不丢失）"""
        try:
            if os.path.exists(config.CHAT_HISTORY_FILE):
                with open(config.CHAT_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                # 恢复 messages（保留 system prompt，追加历史对话）
                for msg in saved:
                    if msg.get("role") in ("user", "assistant"):
                        self.messages.append(msg)
                        self.displayed_messages.append((msg["role"], msg["content"]))
                if self.displayed_messages:
                    self._rerender_all()
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"加载对话历史失败: {e}")

    def _save_chat_history(self):
        """保存对话历史到文件（仅保存 user/assistant 消息，不含 system）"""
        try:
            history = [msg for msg in self.messages if msg.get("role") in ("user", "assistant")]
            with open(config.CHAT_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"保存对话历史失败: {e}")

    # ---------- 思考中状态处理 ----------

    def _set_thinking(self, thinking):
        """切换输入可用状态"""
        self.send_button.setEnabled(not thinking)
        self.input_box.setEnabled(not thinking)

    # ---------- 宠物姓名同步 ----------

    def update_pet_name(self, new_name):
        """宠物改名后同步：更新标题、system prompt、欢迎语上下文"""
        try:
            self.setWindowTitle(f"{new_name} · AI 对话")
            self.title_label.setText(f"与 {new_name} 聊天")
            # 重写 system prompt 中的名字
            if self.messages and self.messages[0].get("role") == "system":
                self.messages[0]["content"] = (
                    f"你是一只可爱的桌面宠物，名字叫「{new_name}」。"
                    "请用可爱、友好、俏皮的语气与主人对话，回复要简短生动，"
                    "适当使用颜文字或表情，让主人感到温暖和陪伴。"
                    "你是主人贴心的伙伴，关心主人的日常，会主动鼓励主人。"
                )
        except Exception:
            pass

    def closeEvent(self, event):
        """窗口关闭时清理线程"""
        if self.worker is not None and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(2000)
        super().closeEvent(event)


if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    window = ChatWindow()
    window.show()
    sys.exit(app.exec_())
