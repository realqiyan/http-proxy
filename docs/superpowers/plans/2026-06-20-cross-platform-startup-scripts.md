# 跨平台启动脚本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在仓库根目录添加 `start.sh`（macOS/Linux）与 `start.bat`（Windows）两个启动脚本，自动探测 Python、创建 `.venv`、安装依赖并前台启动 `proxy_server.py`。

**Architecture:** 两个独立的平台脚本，各自负责 Python 探测 → venv 创建/复用 → `pip install -r requirements.txt` → 前台运行 `proxy_server.py` 并透传用户参数。无共享代码，逻辑各自完整。

**Tech Stack:** POSIX shell（`/bin/sh`）、Windows 批处理（`.bat`）、Python venv、pip。

## Global Constraints

- 单一依赖：`requests>=231`（来自 `requirements.txt`，脚本通过 `pip install -r requirements.txt` 安装，不硬编码版本）。
- venv 目录名固定为 `.venv`，位于仓库根目录（脚本所在目录）。
- `.venv` 已在 `.gitignore` 中，无需改动。
- 脚本以前台方式运行服务，Ctrl+C 退出，依赖 `proxy_server.py` 自身的 SIGTERM/SIGINT 信号处理做优雅关闭。
- 不做后台守护 / start/stop/status 子命令；不提供 PowerShell 脚本；不提供 macOS Finder 双击入口。
- 透传用户参数给 `proxy_server.py`（如 `-p 8080`）。

---

### Task 1: 创建 start.sh（macOS/Linux 启动脚本）

**Files:**
- Create: `start.sh`

**Interfaces:**
- Consumes: `requirements.txt`（仓库根目录）、`proxy_server.py`（仓库根目录）
- Produces: `start.sh`，运行后创建 `.venv/` 并前台启动服务

- [ ] **Step 1: 创建 start.sh 文件**

写入以下完整内容。脚本用 `#!/bin/sh` 保证 POSIX 可移植；通过脚本自身路径定位仓库根目录，不依赖当前工作目录。

```sh
#!/bin/sh
# 跨平台启动脚本 - macOS / Linux
# 自动创建虚拟环境、安装依赖并前台启动 proxy_server.py
# 用法: ./start.sh [proxy_server.py 的参数...]  例如 ./start.sh -p 8080

set -e

# 定位脚本所在目录（仓库根目录），不依赖当前工作目录
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

# ---- 探测 Python 解释器 ----
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        # 确保是 Python 3
        version=$("$candidate" -c 'import sys; print(sys.version_info[0])' 2>/dev/null || echo "0")
        if [ "$version" = "3" ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ERROR] 未找到 Python 3。请先安装："
    echo "  macOS:   brew install python"
    echo "  Ubuntu:  sudo apt install python3"
    echo "  Fedora:  sudo dnf install python3"
    exit 1
fi

echo "[1/3] 使用 Python: $PYTHON ($("$PYTHON" --version 2>&1))"

# ---- 创建虚拟环境（若不存在）----
if [ ! -d ".venv" ]; then
    echo "[2/3] 创建虚拟环境 .venv ..."
    "$PYTHON" -m venv .venv || {
        echo "[ERROR] 创建虚拟环境失败，请检查 Python 是否安装了 venv 模块。"
        exit 1
    }
else
    echo "[2/3] 虚拟环境 .venv 已存在，复用。"
fi

# ---- 安装依赖 ----
echo "[3/3] 安装依赖 (requirements.txt) ..."
.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1 || true
.venv/bin/python -m pip install -r requirements.txt || {
    echo "[ERROR] 依赖安装失败。"
    exit 1
}

# ---- 前台启动服务 ----
echo ""
echo "启动 HTTP Proxy 服务（Ctrl+C 退出）..."
echo "  代理:   http://127.0.0.1:12345/http://httpbin.org/ip"
echo "  看板:   http://127.0.0.1:3420"
echo ""
exec .venv/bin/python proxy_server.py "$@"
```

- [ ] **Step 2: 赋予可执行权限**

Run: `chmod +x start.sh`
Expected: 无输出，`ls -l start.sh` 显示含 `x` 权限位。

- [ ] **Step 3: 语法检查**

Run: `sh -n start.sh`
Expected: 无输出（语法正确）。若有输出则修正。

- [ ] **Step 4: 实际运行验证**

Run: `./start.sh -h 2>&1 | head -20`
Expected: `[1/3] 使用 Python: ...`、`[2/3] 创建虚拟环境 .venv ...`、`[3/3] 安装依赖 ...`，随后显示 `proxy_server.py` 的帮助信息（`-h` 触发 argparse 帮助后退出）。确认 `.venv` 被创建。

若服务因 `-h` 直接打印帮助并退出码非 0 导致 `set -e` 中断也无妨——只要帮助文本出现即说明 venv 与依赖链路打通。

- [ ] **Step 5: 提交**

```bash
git add start.sh
git commit -m "feat: add start.sh cross-platform launcher for macOS/Linux"
```

---

### Task 2: 创建 start.bat（Windows 启动脚本）

**Files:**
- Create: `start.bat`

**Interfaces:**
- Consumes: `requirements.txt`（仓库根目录）、`proxy_server.py`（仓库根目录）
- Produces: `start.bat`，双击或命令行运行后创建 `.venv\` 并前台启动服务

- [ ] **Step 1: 创建 start.bat 文件**

写入以下完整内容。批处理用 `%~dp0` 定位脚本所在目录（仓库根目录），不依赖当前工作目录。

```bat
@echo off
REM 跨平台启动脚本 - Windows
REM 自动创建虚拟环境、安装依赖并前台启动 proxy_server.py
REM 用法: start.bat [proxy_server.py 的参数...]  例如 start.bat -p 8080
setlocal enabledelayedexpansion

REM 定位脚本所在目录（仓库根目录），不依赖当前工作目录
cd /d "%~dp0"

REM ---- 探测 Python 解释器 ----
set "PYTHON="

REM 优先使用 py 启动器
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=py -3"
    goto :found_python
)

REM 回退到 python
python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
    goto :found_python
)

echo [ERROR] 未找到 Python 3。请先安装：
echo   推荐从 https://www.python.org/downloads/ 下载
echo   或运行: winget install Python.Python.3
exit /b 1

:found_python
echo [1/3] 使用 Python: %PYTHON% (%PYTHON% --version 2^>^&1)

REM ---- 创建虚拟环境（若不存在）----
if not exist ".venv\Scripts\python.exe" (
    echo [2/3] 创建虚拟环境 .venv ...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] 创建虚拟环境失败，请检查 Python 是否安装了 venv 模块。
        exit /b 1
    )
) else (
    echo [2/3] 虚拟环境 .venv 已存在，复用。
)

REM ---- 安装依赖 ----
echo [3/3] 安装依赖 ^(requirements.txt^) ...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] 依赖安装失败。
    exit /b 1
)

REM ---- 前台启动服务 ----
echo.
echo 启动 HTTP Proxy 服务（Ctrl+C 退出）...
echo   代理:   http://127.0.0.1:12345/http://httpbin.org/ip
echo   看板:   http://127.0.0.1:3420
echo.
.venv\Scripts\python.exe proxy_server.py %*
```

- [ ] **Step 2: 文件内容静态校验**

Run: `grep -c "proxy_server.py %\*" start.bat`
Expected: 输出 `1`（确认参数透传行存在）。

Run: `grep -c "errorlevel 1" start.bat`
Expected: 输出 `>=2`（venv 创建与 pip 安装两处错误分支都在）。

- [ ] **Step 3: 提交**

```bash
git add start.bat
git commit -m "feat: add start.bat cross-platform launcher for Windows"
```

> 注：本开发环境为 macOS，无法直接执行 `.bat`。Windows 运行时验证由用户在 Windows 机器上完成；静态校验保证脚本结构完整。

---

### Task 3: 更新 README 文档

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: `start.sh`、`start.bat` 的存在与用法
- Produces: README 中说明跨平台一键启动方式

- [ ] **Step 1: 在 README 中找到合适的“快速开始”位置**

Run: `grep -n "python proxy_server.py" README.md`
Expected: 显示 README 中提及直接运行 `proxy_server.py` 的行号，作为插入新小节的锚点。

- [ ] **Step 2: 添加跨平台启动说明**

在 README 现有“快速开始 / 安装”小节内（紧邻 `python proxy_server.py` 说明处）插入以下内容（用 Edit 工具精确替换，保持上下文连贯）：

````markdown
### 一键启动（推荐，跨平台）

仓库提供启动脚本，自动创建虚拟环境、安装依赖并前台启动服务：

```bash
# macOS / Linux
./start.sh

# 指定端口等参数透传给 proxy_server.py
./start.sh -p 8080
```

```bat
:: Windows
start.bat
start.bat -p 8080
```

脚本会在仓库根目录创建 `.venv` 虚拟环境并安装 `requirements.txt` 中的依赖，随后前台运行服务（Ctrl+C 退出）。
````

- [ ] **Step 3: 提交**

```bash
git add README.md
git commit -m "docs: document cross-platform start.sh / start.bat launchers"
```

---

## Self-Review

**1. Spec coverage:**
- 两文件结构（start.sh / start.bat）→ Task 1、Task 2 ✓
- Python 探测（macOS/Linux python3→python；Windows py -3→python）→ Task 1 Step 1、Task 2 Step 1 ✓
- venv 创建/复用 + pip install -r requirements.txt → 两脚本均含 ✓
- 前台启动并透传参数（`"$@"` / `%*`）→ 两脚本均含 ✓
- 错误处理（无 Python / venv 失败 / pip 失败）→ 两脚本均含 ✓
- Ctrl+C 由 proxy_server.py 信号处理负责，脚本不额外处理 → 设计已说明 ✓
- 不改 .gitignore（.venv 已存在）→ Global Constraints 已说明，无对应任务 ✓
- 范围之外项（无守护/无 PowerShell/无双击入口/不重做 systemd）→ 未引入对应任务 ✓

**2. Placeholder scan:** 无 TBD/TODO；每个代码步骤含完整脚本内容；命令步骤含期望输出。✓

**3. Type/名称一致性:** start.sh 使用 `.venv/bin/python`，start.bat 使用 `.venv\Scripts\python.exe`，与各平台 venv 布局一致；两者均调用 `proxy_server.py` 与 `requirements.txt`，文件名一致。✓
