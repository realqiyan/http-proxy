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
for /f "tokens=*" %%v in ('%PYTHON% --version 2^>^&1') do (
    echo [1/3] 使用 Python: %PYTHON% ^(%%v^)
)

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
