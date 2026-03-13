#!/usr/bin/env python3
"""
HTTP Forwarding Server - HTTP 转发服务器

使用方式：
  http://127.0.0.1:12345/http://httpbin.org/ip
  http://127.0.0.1:12345/https://httpbin.org/ip

功能特性：
- 完整的请求/响应日志记录
- 从 URL 路径解析目标地址并转发请求
- 支持流式传输（chunked encoding, SSE）
- 并发处理多个请求
- SQLite 持久化存储
- Web Dashboard 看板
- 后台运行与进程守护
"""

import argparse
import http.server
import socketserver
import os
import sys
import threading
import signal
import time
import traceback
import subprocess
from datetime import datetime

from utils.colors import Colors
from utils.format import format_size, format_duration
from core.database import DatabaseManager
from core.logger import RequestLogger
from core.handlers import ForwardingHandler
from dashboard.server import start_dashboard_server


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """支持多线程的 TCP 服务器"""
    allow_reuse_address = True
    daemon_threads = True
    log_file = None
    logger = None
    db_manager = None


# 全局变量用于信号处理
_server = None
_shutdown_requested = False
PID_FILE = 'proxy.pid'


def signal_handler(signum, frame):
    """信号处理器"""
    global _shutdown_requested
    _shutdown_requested = True
    if _server:
        print(f"\n{Colors.YELLOW}收到终止信号，正在关闭...{Colors.RESET}")
        _server.shutdown()


def write_pid():
    """写入 PID 文件"""
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))


def remove_pid():
    """删除 PID 文件"""
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)


def is_running():
    """检查服务是否正在运行"""
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        # 检查进程是否存在
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def stop_server():
    """停止服务器"""
    if not os.path.exists(PID_FILE):
        print(f"{Colors.RED}服务未运行{Colors.RESET}")
        return False

    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())

        # 发送 SIGTERM 信号
        os.kill(pid, signal.SIGTERM)
        print(f"{Colors.YELLOW}正在停止服务 (PID: {pid})...{Colors.RESET}")

        # 等待进程结束
        for _ in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except ProcessLookupError:
                print(f"{Colors.GREEN}服务已停止{Colors.RESET}")
                remove_pid()
                return True

        # 如果进程还在，强制杀死
        try:
            os.kill(pid, signal.SIGKILL)
            print(f"{Colors.YELLOW}已强制停止服务{Colors.RESET}")
        except ProcessLookupError:
            pass

        remove_pid()
        return True

    except (ValueError, ProcessLookupError, PermissionError) as e:
        print(f"{Colors.RED}停止失败: {e}{Colors.RESET}")
        remove_pid()
        return False


def run_server(args):
    """运行服务器"""
    global _server

    # 写入 PID
    write_pid()

    # 创建数据库管理器
    db_manager = DatabaseManager(args.db_file)

    # 创建日志记录器
    logger = RequestLogger(args.log_file, db_manager, enable_file_log=args.enable_log_file)

    # 启动 Dashboard 服务器（独立线程）
    if not args.no_web:
        dashboard_thread = threading.Thread(
            target=start_dashboard_server,
            args=(args.web_host, args.web_port, db_manager),
            daemon=True
        )
        dashboard_thread.start()

    # 启动代理服务器
    _server = ThreadedTCPServer(('0.0.0.0', args.port), ForwardingHandler)
    _server.log_file = args.log_file
    _server.logger = logger
    _server.db_manager = db_manager

    print(f"\n{Colors.BOLD}{Colors.CYAN}HTTP Forwarding Server{Colors.RESET}")
    print(f"{Colors.GREEN}✓{Colors.RESET} 代理服务器已启动 (PID: {os.getpid()})")
    print(f"{Colors.BLUE}→{Colors.RESET} 代理端口: {Colors.YELLOW}{args.port}{Colors.RESET}")
    if args.enable_log_file:
        print(f"{Colors.BLUE}→{Colors.RESET} 日志文件: {Colors.YELLOW}{args.log_file}{Colors.RESET}")
    print(f"{Colors.BLUE}→{Colors.RESET} 数据库: {Colors.YELLOW}{args.db_file}{Colors.RESET}")

    if not args.no_web:
        print(f"\n{Colors.BOLD}{Colors.CYAN}Dashboard{Colors.RESET}")
        print(f"{Colors.GREEN}✓{Colors.RESET} 看板服务器已启动")
        print(f"{Colors.BLUE}→{Colors.RESET} 访问地址: {Colors.YELLOW}http://{args.web_host if args.web_host != '0.0.0.0' else '127.0.0.1'}:{args.web_port}{Colors.RESET}")
    print(f"\n{Colors.BOLD}使用方式:{Colors.RESET}")
    print(f"  {Colors.DIM}http://127.0.0.1:{args.port}/http://example.com{Colors.RESET}")
    print(f"  {Colors.DIM}http://127.0.0.1:{args.port}/https://example.com{Colors.RESET}")
    print(f"\n{Colors.DIM}停止服务: python proxy_server.py stop{Colors.RESET}\n")

    # 记录启动日志
    if args.enable_log_file:
        with open(args.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] SERVER STARTED on port {args.port} (PID: {os.getpid()})\n")
            if not args.no_web:
                f.write(f"Dashboard: http://{args.web_host}:{args.web_port}\n")
            f.write(f"{'='*60}\n")

    try:
        _server.serve_forever()
    finally:
        _server.server_close()
        remove_pid()


def daemon_main(args):
    """守护进程主循环"""
    global _shutdown_requested

    restart_count = 0

    while not _shutdown_requested:
        try:
            run_server(args)
        except KeyboardInterrupt:
            break
        except Exception as e:
            restart_count += 1
            print(f"\n{Colors.RED}[Daemon] 服务异常退出: {e}{Colors.RESET}")
            print(f"{Colors.RED}[Daemon] 堆栈跟踪:\n{traceback.format_exc()}{Colors.RESET}")

            if _shutdown_requested:
                break

            print(f"{Colors.YELLOW}[Daemon] {args.restart_delay} 秒后自动重启... (重启次数: {restart_count}){Colors.RESET}")
            time.sleep(args.restart_delay)

    print(f"\n{Colors.YELLOW}[Daemon] 服务已停止{Colors.RESET}")

    if args.enable_log_file:
        with open(args.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] SERVER STOPPED\n")
            f.write(f"Total Restarts: {restart_count}\n")
            f.write(f"{'='*60}\n\n")


def start_daemon(args):
    """启动守护进程"""
    if is_running():
        with open(PID_FILE, 'r') as f:
            pid = f.read().strip()
        print(f"{Colors.RED}服务已在运行中 (PID: {pid}){Colors.RESET}")
        print(f"{Colors.YELLOW}如需重启，请先执行: python proxy_server.py stop{Colors.RESET}")
        return

    # 设置信号处理
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # 启动守护进程
    daemon_main(args)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='HTTP Forwarding Server - HTTP 转发服务器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用方式:
  在 URL 前添加代理服务器地址:
    http://127.0.0.1:12345/http://httpbin.org/ip
    http://127.0.0.1:12345/https://httpbin.org/ip

Dashboard:
  访问 http://127.0.0.1:3420 查看请求看板

命令:
  start       启动服务（默认命令，可省略）
  stop        停止服务
  status      查看服务状态

示例:
  %(prog)s                           # 启动服务
  %(prog)s start                     # 启动服务
  %(prog)s stop                      # 停止服务
  %(prog)s status                    # 查看状态
  %(prog)s -p 8080                   # 指定端口启动
  %(prog)s --no-web                  # 禁用 Dashboard 启动
        """
    )
    parser.add_argument(
        'command',
        nargs='?',
        default='start',
        choices=['start', 'stop', 'status'],
        help='命令: start(启动), stop(停止), status(状态)'
    )
    parser.add_argument(
        '-p', '--port',
        type=int,
        default=12345,
        help='代理服务器端口 (默认: 12345)'
    )
    parser.add_argument(
        '--no-web',
        action='store_true',
        help='禁用 Web Dashboard 看板'
    )
    parser.add_argument(
        '--web-host',
        default='127.0.0.1',
        help='Dashboard 绑定地址 (默认: 127.0.0.1, 对外开放可设为 0.0.0.0)'
    )
    parser.add_argument(
        '--web-port',
        type=int,
        default=3420,
        help='Dashboard 看板端口 (默认: 3420)'
    )
    parser.add_argument(
        '--no-color',
        action='store_true',
        help='禁用终端颜色输出'
    )
    parser.add_argument(
        '--log-file',
        default='logs/proxy.log',
        help='日志文件路径 (默认: logs/proxy.log)'
    )
    parser.add_argument(
        '--enable-log-file',
        action='store_true',
        help='启用日志文件输出 (默认: 关闭)'
    )
    parser.add_argument(
        '--db-file',
        default='data/proxy.db',
        help='数据库文件路径 (默认: data/proxy.db)'
    )
    parser.add_argument(
        '--restart-delay',
        type=int,
        default=3,
        help='自动重启延迟秒数 (默认: 3)'
    )

    args = parser.parse_args()

    # 禁用颜色
    if args.no_color:
        Colors.disable()

    # 确保目录存在
    if args.enable_log_file:
        log_dir = os.path.dirname(args.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

    db_dir = os.path.dirname(args.db_file)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # 处理命令
    if args.command == 'stop':
        stop_server()

    elif args.command == 'status':
        if is_running():
            with open(PID_FILE, 'r') as f:
                pid = f.read().strip()
            print(f"{Colors.GREEN}服务运行中 (PID: {pid}){Colors.RESET}")
            # 尝试获取统计信息
            try:
                import urllib.request
                with urllib.request.urlopen(f"http://127.0.0.1:{args.web_port}/api/stats", timeout=2) as resp:
                    stats = resp.read().decode()
                    import json
                    data = json.loads(stats)
                    print(f"  总请求: {data['total']}, 成功: {data['success']}, 错误: {data['errors']}")
            except:
                pass
        else:
            print(f"{Colors.RED}服务未运行{Colors.RESET}")

    elif args.command == 'start':
        start_daemon(args)


if __name__ == '__main__':
    main()