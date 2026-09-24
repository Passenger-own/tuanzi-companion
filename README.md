# 团子陪伴 · 桌面萌宠

一只常驻 macOS 桌面的毛绒猫咪，陪你办公、提醒你喝水久坐、还能和你 AI 对话。基于 PyQt5 开发，7 套治愈动画 + 13 项实用功能。

## 功能特性

### 🐱 猫咪交互
- **7 套动作动画**：idle 待机、happy 开心、eat 喝水、stretch 伸懒腰、lie_back 躺平撒娇、lie_side 侧躺、sleep 睡觉
- **鼠标交互**：单击眨眼、三击躺平撒娇、拖拽移动、悬停开心
- **气泡对话**：每个动作配套软萌气泡文案，3 秒自动消失

### 🎯 专注模式
- **轻度专注**：侧躺陪伴，屏蔽自动挥手动画
- **深度专注**：熟睡屏蔽所有交互，沉浸式办公
- **手动结束专注**：伸懒腰过渡 + 专属气泡

### 🛠️ 办公工具
- **AI 对话**：接入 DeepSeek API，猫咪化身聊天搭子
- **待办清单**：新增 / 勾选 / 删除 / 清空已完成，本地持久化
- **计算器**：四则运算，结果以气泡形式反馈
- **随笔记事本**：多行文本，自动保存
- **Mac 快捷键面板**：窗口 / 文本 / 截图分类速查

### ⏰ 健康提醒
- **喝水提醒**：自定义间隔（1–90 分钟），到点猫咪喝水动画提醒
- **久坐提醒**：自定义间隔，到点伸懒腰动画提醒
- **喝水打卡**：手动打卡计数，今日饮水一目了然
- **环形进度条**：猫咪头顶常驻，展示距下次提醒剩余时长

### ⚙️ 基础功能
- **修改宠物昵称**：自定义猫咪名字，重启不丢失
- **交互说明**：内置操作引导
- **窗口置顶**：猫咪永远在最上层陪伴

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.8+ | 运行环境 |
| PyQt5 | GUI 框架（无边框透明窗口 + 毛玻璃 UI） |
| QMediaPlayer / QMovie | 视频 / GIF 动画渲染 |
| requests | DeepSeek API 调用 |
| 本地 JSON | 待办、笔记、提醒状态持久化 |

## 环境要求

- **操作系统**：macOS（仅支持 macOS）
- **Python**：3.8 或更高版本
- **网络**：首次运行需联网安装依赖；AI 对话功能需联网

## 快速开始

### 1. 下载

下载 `桌面宠物.zip` 并解压，得到 `桌面宠物` 文件夹。

### 2. 配置 API Key（AI 对话功能需要）

两种方式任选其一：

**方式一：环境变量（推荐，不修改源码）**
```bash
export DEEPSEEK_API_KEY="sk-你的DeepSeek密钥"
```

**方式二：直接编辑 `config.py`**
```python
DEEPSEEK_API_KEY = "sk-你的DeepSeek密钥"
```

> 获取 API Key：[https://platform.deepseek.com/](https://platform.deepseek.com/)

### 3. 运行

```bash
cd 桌面宠物
bash run.sh
```

首次运行会自动创建虚拟环境并安装依赖（约 30 秒），之后秒开。

启动日志位置：`~/Library/Application Support/桌面宠物/launch.log`

## 右键菜单（13 项）

| 菜单项 | 功能 |
|--------|------|
| AI 对话 | 打开 AI 聊天窗口 |
| 手动结束专注模式 | 退出专注，播放伸懒腰动画 |
| 轻度专注 | 开启 / 关闭轻度专注 |
| 深度专注 | 开启 / 关闭深度专注 |
| 打开待办清单 | 待办事项管理 |
| 打开计算器 | 简易计算器 |
| 打开随笔记事本 | 快速记事 |
| 电脑快捷操作面板 | Mac 快捷键速查 |
| 健康提醒设置 | 喝水 / 久坐提醒间隔配置 |
| 喝水打卡 | 记录今日饮水 |
| 设置宠物姓名 | 修改猫咪昵称 |
| 交互说明 | 查看操作指南 |
| 退出程序 | 关闭桌面宠物 |

## 项目结构

```
桌面宠物/
├── run.sh                # 启动脚本（自动创建 venv + 安装依赖）
├── main.py               # 应用入口
├── config.py             # 全局配置（含 API Key）
├── pet_window.py         # 主窗口：猫咪渲染 + 右键菜单 + 状态机
├── ai_chat.py            # AI 对话模块（DeepSeek API）
├── reminder.py           # 健康提醒系统 + 环形进度条
├── tools_panel.py        # 工具面板集合（待办 / 计算器 / 笔记 / 快捷键）
├── glass_widgets.py      # 毛玻璃 UI 组件库
├── animations.json       # 动画配置
├── requirements.txt      # Python 依赖
└── assets/video/         # 7 套猫咪 GIF 动画素材
    ├── idle.gif happy.gif eat.gif stretch.gif
    └── lie_back.gif lie_side.gif sleep.gif
```

## 数据存储

所有用户数据保存在 `~/Library/Application Support/桌面宠物/data/`：

| 文件 | 内容 |
|------|------|
| `todo.json` | 待办清单 |
| `notes.json` | 记事本内容 |
| `pet_config.json` | 宠物昵称等配置 |
| `chat_history.json` | AI 对话历史 |
| `reminder_state.json` | 健康提醒设置与打卡记录 |

## 注意事项

- 本项目仅支持 macOS，不支持 Windows / Linux
- 首次运行需联网安装 PyQt5 等依赖
- AI 对话功能需自行配置 DeepSeek API Key
- 虚拟环境安装在 `~/Library/Application Support/桌面宠物/venv`，不占用安装包目录

## License

MIT License
