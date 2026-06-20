# 跨平台启动脚本设计

日期：2026-06-20

## 目标

在仓库根目录添加跨平台启动脚本，自动探测 Python 解释器、创建虚拟环境、安装依赖（`requests`），然后前台启动 `proxy_server.py`。覆盖 macOS、Linux、Windows 三个平台。Ctrl+C 退出。

## 背景

当前项目仅支持 Linux systemd 用户服务（`proxy_server.py install/uninstall`），默认运行方式是前台 `python proxy_server.py`。单一依赖 `requests`（见 `requirements.txt`）。需要一组开箱即用的启动脚本，让任意平台用户无需手动装依赖即可运行。

## 文件结构

```
http-proxy/
├── start.sh      # macOS / Linux（POSIX shell）
└── start.bat     # Windows 批处理
```

两个文件，各平台一份。不提供 `start.command` 等 macOS Finder 双击入口——用户在终端运行即可。

## Python 解释器探测

- **macOS / Linux（start.sh）**：优先 `python3`，回退 `python`；找不到则提示用户安装（macOS: `brew install python`；Linux: `apt install python3` / `dnf install python3`）并以非零码退出。
- **Windows（start.bat）**：优先 `py -3` 启动器，回退 `python`；找不到则提示安装 Python（建议从 python.org 下载或 `winget install Python.Python.3`）并以非零码退出。

## 虚拟环境与依赖

1. 在仓库根目录创建 `.venv`（若不存在）。用脚本所在目录的绝对路径定位仓库根，不依赖当前工作目录。
2. 用 venv 内的解释器执行 `python -m pip install -r requirements.txt`。pip 幂等，已满足的依赖会跳过，因此每次启动都运行也能快速完成并自动补全缺失依赖。
3. venv 创建失败或 pip 安装失败时，打印清晰错误信息并退出，不继续启动服务。

## 启动服务

依赖就绪后，用 venv 的 Python 前台运行 `proxy_server.py`，并透传用户额外参数：

- Unix（start.sh）：`.venv/bin/python proxy_server.py "$@"`
- Windows（start.bat）：`.venv\Scripts\python.exe proxy_server.py %*`

例如 `./start.sh -p 8080` 会以 8080 端口启动。

## 错误处理

- 无 Python → 友好平台化提示 + 非零退出码。
- venv 创建失败 / pip 失败 → 提示原因 + 退出。
- 服务自身的 Ctrl+C 优雅关闭由 `proxy_server.py` 已有的信号处理负责（SIGTERM/SIGINT），脚本无需额外处理。

## .gitignore

`.venv` 已在 `.gitignore` 中，无需修改。

## 范围之外（YAGNI）

- 不做后台守护 / start/stop/status 子命令（保持前台启动，与现有默认行为一致）。
- 不做 PowerShell 脚本。
- 不做 macOS Finder 双击入口。
- 不重复实现 Linux systemd 安装（已有 `proxy_server.py install`）。
