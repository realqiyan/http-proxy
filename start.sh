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
