#!/bin/bash
# ============================================
# 桌面宠物 - 文件夹版启动脚本
# 运行: bash run.sh  或  ./run.sh
# 首次启动自动安装依赖
# ============================================

# 确保 UTF-8 编码（中文路径/文件名）
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# ── 定位项目目录（脚本所在目录） ──
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${SELF_DIR}"

# 可写数据目录（macOS 标准位置，venv 放这里保证可写与跨机器移动）
SUPPORT_DIR="$HOME/Library/Application Support/桌面宠物"
LAUNCH_LOG="${SUPPORT_DIR}/launch.log"
VENV_DIR="${SUPPORT_DIR}/venv"

mkdir -p "${SUPPORT_DIR}" 2>/dev/null || true

# 日志函数
log() {
    echo "$1" 2>/dev/null || true
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "${LAUNCH_LOG}" 2>/dev/null || true
}

log "========== 桌面宠物启动（文件夹版） =========="
log "PROJECT_DIR: ${PROJECT_DIR}"
log "VENV_DIR: ${VENV_DIR}"

# ── Python 路径检测 ──
if [ -f "${VENV_DIR}/bin/python" ]; then
    PYTHON="${VENV_DIR}/bin/python"
    log "使用 venv Python: ${PYTHON}"
else
    # 查找系统 python3
    PYTHON=""
    for p in python3 python3.12 python3.11 python3.10 python3.9 python3.8; do
        if command -v "${p}" &>/dev/null; then
            PYTHON="$(command -v "${p}")"
            break
        fi
    done

    if [ -z "${PYTHON}" ]; then
        log "ERROR: 未找到 python3"
        osascript -e 'display alert "桌面宠物启动失败" message "未找到 Python 3，请先安装 Python 3.8 或更高版本。\n\n下载地址: python.org/downloads" as critical' 2>/dev/null || true
        exit 1
    fi

    log "首次启动，使用系统 Python: ${PYTHON}"
    log "正在创建虚拟环境..."

    # 创建虚拟环境（--copies 提升可移植性）
    "${PYTHON}" -m venv --copies "${VENV_DIR}" 2>&1 >> "${LAUNCH_LOG}" || \
    "${PYTHON}" -m venv "${VENV_DIR}" 2>&1 >> "${LAUNCH_LOG}" || {
        log "ERROR: venv 创建失败"
        osascript -e 'display alert "桌面宠物启动失败" message "创建虚拟环境失败，请检查 Python 安装是否完整。" as critical' 2>/dev/null || true
        exit 1
    }

    # 安装依赖
    log "正在安装依赖..."
    "${VENV_DIR}/bin/pip" install --quiet -r "${PROJECT_DIR}/requirements.txt" 2>&1 >> "${LAUNCH_LOG}" || {
        log "WARN: 依赖安装可能不完整，尝试继续运行"
    }

    # 检查 PyQt5
    if ! "${VENV_DIR}/bin/python" -c "import PyQt5" 2>/dev/null; then
        log "WARN: PyQt5 未安装成功，重试..."
        "${VENV_DIR}/bin/pip" install PyQt5 2>&1 >> "${LAUNCH_LOG}" || true
    fi

    PYTHON="${VENV_DIR}/bin/python"
    log "初始化完成！"
fi

# ── Qt 插件路径设置 ──
QT_PLUGIN_DIRS=$("${PYTHON}" -c "
import os, sys
dirs = []
try:
    import PyQt5
    pyqt5_dir = os.path.dirname(PyQt5.__file__)
    p1 = os.path.join(pyqt5_dir, 'Qt5', 'plugins')
    if os.path.isdir(p1): dirs.append(p1)
    p2 = os.path.join(pyqt5_dir, 'Qt5', 'plugins', 'platforms')
    if os.path.isdir(p2): dirs.append(p2)
    p3 = os.path.join(pyqt5_dir, 'plugins')
    if os.path.isdir(p3): dirs.append(p3)
except Exception:
    pass
try:
    from PyQt5.QtCore import QLibraryInfo
    plugins_dir = QLibraryInfo.location(QLibraryInfo.PluginsPath)
    if plugins_dir and os.path.isdir(plugins_dir):
        dirs.append(plugins_dir)
        platforms_dir = os.path.join(plugins_dir, 'platforms')
        if os.path.isdir(platforms_dir):
            dirs.append(platforms_dir)
except Exception:
    pass
print(':'.join(dirs) if dirs else '')
" 2>/dev/null || echo "")

if [ -n "${QT_PLUGIN_DIRS}" ]; then
    export QT_PLUGIN_PATH="${QT_PLUGIN_DIRS}:${QT_PLUGIN_PATH:-}"
    export QT_QPA_PLATFORM_PLUGIN_PATH="${QT_PLUGIN_DIRS}:${QT_QPA_PLATFORM_PLUGIN_PATH:-}"
fi

# ── 设置工作目录为项目目录，启动应用 ──
cd "${PROJECT_DIR}"
log "启动 main.py..."
"${PYTHON}" main.py 2>&1 | while IFS= read -r line; do
    log "[app] ${line}"
done

EXIT_CODE=${PIPESTATUS[0]:-0}
log "应用退出，代码: ${EXIT_CODE}"
exit ${EXIT_CODE}
