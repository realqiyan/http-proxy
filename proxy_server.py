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
"""

import argparse
import http.server
import socketserver
import os
import sys
import threading
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

示例:
  %(prog)s                           # 使用默认端口 12345，Dashboard 端口 3420
  %(prog)s -p 8080                   # 使用端口 8080
  %(prog)s --no-web                  # 禁用 Dashboard
  %(prog)s --web-host 0.0.0.0        # Dashboard 对外开放
  %(prog)s --web-port 9090           # Dashboard 端口 9090
  %(prog)s --enable-log-file         # 启用日志文件输出
  %(prog)s -p 8080 --no-color        # 禁用颜色输出
        """
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
    try:
        server = ThreadedTCPServer(('0.0.0.0', args.port), ForwardingHandler)
        server.log_file = args.log_file
        server.logger = logger
        server.db_manager = db_manager

        print(f"\n{Colors.BOLD}{Colors.CYAN}HTTP Forwarding Server{Colors.RESET}")
        print(f"{Colors.GREEN}✓{Colors.RESET} 代理服务器已启动")
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
        print(f"\n{Colors.DIM}按 Ctrl+C 停止服务器{Colors.RESET}\n")

        # 记录启动日志
        if args.enable_log_file:
            with open(args.log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] SERVER STARTED on port {args.port}\n")
                if not args.no_web:
                    f.write(f"Dashboard: http://{args.web_host}:{args.web_port}\n")
                f.write(f"{'='*60}\n")

        server.serve_forever()

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}正在关闭服务器...{Colors.RESET}")
        if args.enable_log_file:
            with open(args.log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] SERVER STOPPED\n")
                f.write(f"{'='*60}\n\n")
        server.shutdown()
        server.server_close()
    except OSError as e:
        if e.errno == 98:
            print(f"{Colors.RED}错误: 端口 {args.port} 已被占用{Colors.RESET}")
        else:
            print(f"{Colors.RED}错误: {e}{Colors.RESET}")
        sys.exit(1)


if __name__ == '__main__':
    main()