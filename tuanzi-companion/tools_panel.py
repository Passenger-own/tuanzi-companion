"""
桌面宠物 - 内置工具面板
包含待办事项、计算器和随笔三个功能
"""

import os
import json
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QTextEdit, QLabel,
    QGridLayout, QShortcut
)

from config import DATA_DIR, TODO_FILE, NOTES_FILE


# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)


# ==================== 全局 QSS 样式 ====================
GLOBAL_QSS = """
QWidget {
    font-family: "Microsoft YaHei", "PingFang SC", "Arial";
    font-size: 13px;
    color: #2c3e50;
}

QTabWidget::pane {
    border: 1px solid #dcdfe6;
    border-radius: 6px;
    background: #ffffff;
    top: -1px;
}

QTabBar::tab {
    background: #f5f7fa;
    color: #606266;
    padding: 8px 22px;
    margin-right: 2px;
    border: 1px solid #dcdfe6;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}

QTabBar::tab:selected {
    background: #ffffff;
    color: #409eff;
    border-color: #409eff;
}

QTabBar::tab:hover:!selected {
    background: #ecf5ff;
}

QLineEdit, QTextEdit, QListWidget {
    border: 1px solid #dcdfe6;
    border-radius: 6px;
    padding: 6px 8px;
    background: #ffffff;
    selection-background-color: #409eff;
}

QLineEdit:focus, QTextEdit:focus, QListWidget:focus {
    border: 1px solid #409eff;
}

QPushButton {
    background: #409eff;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
}

QPushButton:hover {
    background: #66b1ff;
}

QPushButton:pressed {
    background: #3a8ee6;
}

QPushButton[cssClass="danger"] {
    background: #f56c6c;
}

QPushButton[cssClass="danger"]:hover {
    background: #f78989;
}

QPushButton[cssClass="default"] {
    background: #909399;
}

QPushButton[cssClass="default"]:hover {
    background: #a6a9ad;
}

QPushButton[cssClass="calc"] {
    background: #f5f7fa;
    color: #2c3e50;
    font-size: 16px;
    font-weight: bold;
    padding: 12px 0;
    border: 1px solid #dcdfe6;
}

QPushButton[cssClass="calc"]:hover {
    background: #ecf5ff;
    color: #409eff;
    border-color: #409eff;
}

QPushButton[cssClass="calc_op"] {
    background: #faecd8;
    color: #e6a23c;
}

QPushButton[cssClass="calc_op"]:hover {
    background: #fdf6ec;
    color: #cf9236;
}

QPushButton[cssClass="calc_eq"] {
    background: #67c23a;
    color: #ffffff;
}

QPushButton[cssClass="calc_eq"]:hover {
    background: #85ce61;
}

QPushButton[cssClass="calc_clear"] {
    background: #f56c6c;
    color: #ffffff;
}

QPushButton[cssClass="calc_clear"]:hover {
    background: #f78989;
}
"""


def _set_css_class(widget, css_class):
    """为控件设置 cssClass 属性，便于 QSS 选择"""
    widget.setProperty("cssClass", css_class)


# ==================== 待办事项页面 ====================
class TodoTab(QWidget):
    """待办事项标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._todos = []  # [{"text": str, "done": bool}, ...]
        self._init_ui()
        self._load_todos()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 顶部输入区
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("输入待办事项后按回车或点击添加...")
        self.input_edit.returnPressed.connect(self._add_todo)
        top_layout.addWidget(self.input_edit, 1)

        self.add_btn = QPushButton("添加")
        self.add_btn.setFixedWidth(72)
        self.add_btn.clicked.connect(self._add_todo)
        top_layout.addWidget(self.add_btn)
        layout.addLayout(top_layout)

        # 待办列表
        self.list_widget = QListWidget()
        self.list_widget.setItemAlignment(Qt.AlignLeft)
        self.list_widget.itemChanged.connect(self._toggle_done)
        layout.addWidget(self.list_widget, 1)

        # 底部按钮区
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch(1)

        self.delete_done_btn = QPushButton("删除已完成")
        _set_css_class(self.delete_done_btn, "default")
        self.delete_done_btn.clicked.connect(self._delete_done)
        bottom_layout.addWidget(self.delete_done_btn)

        self.clear_btn = QPushButton("清空")
        _set_css_class(self.clear_btn, "danger")
        self.clear_btn.clicked.connect(self._clear_all)
        bottom_layout.addWidget(self.clear_btn)
        layout.addLayout(bottom_layout)

    # ----- 数据操作 -----
    def _add_todo(self):
        text = self.input_edit.text().strip()
        if not text:
            return
        self._todos.append({"text": text, "done": False})
        self.input_edit.clear()
        self._refresh_list()
        self._save_todos()

    def _toggle_done(self, item):
        row = self.list_widget.row(item)
        if 0 <= row < len(self._todos):
            self._todos[row]["done"] = (
                item.checkState() == Qt.Checked
            )
            self._refresh_list(row)
            self._save_todos()

    def _delete_done(self):
        self._todos = [t for t in self._todos if not t["done"]]
        self._refresh_list()
        self._save_todos()

    def _clear_all(self):
        self._todos = []
        self._refresh_list()
        self._save_todos()

    # ----- 列表刷新 -----
    def _refresh_list(self, keep_row=None):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for todo in self._todos:
            item = QListWidgetItem(todo["text"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if todo["done"] else Qt.Unchecked)
            if todo["done"]:
                # 已完成项显示删除线效果
                font = item.font()
                font.setStrikeOut(True)
                item.setFont(font)
                item.setForeground(Qt.gray)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        if keep_row is not None and 0 <= keep_row < self.list_widget.count():
            self.list_widget.setCurrentRow(keep_row)

    # ----- 持久化 -----
    def _load_todos(self):
        if os.path.exists(TODO_FILE):
            try:
                with open(TODO_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._todos = [
                        t for t in data
                        if isinstance(t, dict)
                        and "text" in t
                        and "done" in t
                    ]
            except (json.JSONDecodeError, OSError):
                self._todos = []
        self._refresh_list()

    def _save_todos(self):
        try:
            with open(TODO_FILE, "w", encoding="utf-8") as f:
                json.dump(self._todos, f, ensure_ascii=False, indent=2)
        except OSError:
            pass


# ==================== 计算器页面 ====================
class CalculatorTab(QWidget):
    """计算器标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = "0"        # 当前输入
        self._stored = None        # 存储的上一操作数
        self._operator = None      # 当前运算符
        self._reset_display = False  # 下次输入是否重置显示屏
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 显示屏
        self.display = QLineEdit("0")
        self.display.setReadOnly(True)
        self.display.setAlignment(Qt.AlignRight)
        self.display.setStyleSheet(
            "QLineEdit { font-size: 24px; padding: 12px; "
            "border: 1px solid #dcdfe6; border-radius: 6px; "
            "background: #fafafa; }"
        )
        layout.addWidget(self.display)

        # 按钮网格
        grid = QGridLayout()
        grid.setSpacing(6)

        # 按钮定义: (text, row, col, cssClass)
        buttons = [
            ("C", 0, 0, "calc_clear"),
            ("=", 0, 1, "calc_eq"),
            ("/", 0, 2, "calc_op"),
            ("*", 0, 3, "calc_op"),
            ("7", 1, 0, "calc"),
            ("8", 1, 1, "calc"),
            ("9", 1, 2, "calc"),
            ("-", 1, 3, "calc_op"),
            ("4", 2, 0, "calc"),
            ("5", 2, 1, "calc"),
            ("6", 2, 2, "calc"),
            ("+", 2, 3, "calc_op"),
            ("1", 3, 0, "calc"),
            ("2", 3, 1, "calc"),
            ("3", 3, 2, "calc"),
            ("0", 4, 0, "calc"),
            (".", 4, 1, "calc"),
        ]

        for text, row, col, css_class in buttons:
            btn = QPushButton(text)
            _set_css_class(btn, css_class)
            btn.clicked.connect(lambda _, t=text: self._on_button_clicked(t))
            if text == "0":
                grid.addWidget(btn, row, col, 1, 2)
            else:
                grid.addWidget(btn, row, col)

        layout.addLayout(grid, 1)

    # ----- 计算逻辑 -----
    def _on_button_clicked(self, text):
        if text in "0123456789":
            self._input_digit(text)
        elif text == ".":
            self._input_dot()
        elif text in "+-*/":
            self._input_operator(text)
        elif text == "=":
            self._calculate()
        elif text == "C":
            self._clear()

        self._update_display()

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
        # 若已有运算符且未重置，则先计算
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

    def _clear(self):
        self._current = "0"
        self._stored = None
        self._operator = None
        self._reset_display = False

    def _update_display(self):
        self.display.setText(self._current)


# ==================== 随笔页面 ====================
class NotesTab(QWidget):
    """随笔标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._load_notes()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 文本编辑区
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("在这里记录你的灵感与想法...")
        layout.addWidget(self.text_edit, 1)

        # 底部状态栏
        bottom_layout = QHBoxLayout()
        self.status_label = QLabel("上次保存：尚未保存")
        self.status_label.setStyleSheet("color: #909399;")
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addStretch(1)

        self.save_btn = QPushButton("保存")
        self.save_btn.setFixedWidth(80)
        self.save_btn.clicked.connect(self._save_notes)
        bottom_layout.addWidget(self.save_btn)
        layout.addLayout(bottom_layout)

        # Ctrl+S 快捷键保存（作用于整个随笔页面，文本编辑区聚焦时也可触发）
        self.save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.save_shortcut.activated.connect(self._save_notes)

    # ----- 持久化 -----
    def _load_notes(self):
        if os.path.exists(NOTES_FILE):
            try:
                with open(NOTES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "content" in data:
                    self.text_edit.setPlainText(data["content"])
                if isinstance(data, dict) and "saved_at" in data:
                    self._update_status(data["saved_at"])
            except (json.JSONDecodeError, OSError):
                pass

    def _save_notes(self):
        content = self.text_edit.toPlainText()
        saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = {"content": content, "saved_at": saved_at}
        try:
            with open(NOTES_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._update_status(saved_at)
        except OSError:
            pass

    def _update_status(self, saved_at):
        self.status_label.setText(f"上次保存：{saved_at}")


# ==================== 工具面板主窗口 ====================
class ToolsPanel(QWidget):
    """工具面板主窗口，包含三个功能标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("工具面板")
        self.setFixedSize(450, 550)
        self._init_ui()
        self.setStyleSheet(GLOBAL_QSS)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tab_widget = QTabWidget()
        self.todo_tab = TodoTab()
        self.calculator_tab = CalculatorTab()
        self.notes_tab = NotesTab()

        self.tab_widget.addTab(self.todo_tab, "待办")
        self.tab_widget.addTab(self.calculator_tab, "计算器")
        self.tab_widget.addTab(self.notes_tab, "随笔")
        layout.addWidget(self.tab_widget)


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    panel = ToolsPanel()
    panel.show()
    sys.exit(app.exec_())
