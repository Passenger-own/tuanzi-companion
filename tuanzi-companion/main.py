"""
桌面宠物 - 主入口
启动: python main.py
"""
import sys
import os

# 确保能找到同目录下的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

import config

# macOS 下高 DPI 支持
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("桌面宠物")

    from pet_window import PetWindow
    pet = PetWindow()

    # 初始位置：屏幕右下角
    screen = app.primaryScreen().geometry()
    pet.move(
        screen.width() - config.PET_SIZE - 50,
        screen.height() - config.PET_SIZE - 80
    )

    pet.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
