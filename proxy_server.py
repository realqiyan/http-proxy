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
- Linux systemd 用户服务支持
"""

import argparse
import http.server
import socketserver
import os
import sys
import threading
import signal
import subprocess
from datetime import datetime

from utils.colors import Colors
from core.database import DatabaseManager
from core.logger import RequestLogger
from core.handlers import ForwardingHandler
from dashboard.server import DashboardServer


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """支持多线程的 TCP 服务器"""
    allow_reuse_address = True
    daemon_threads = True
    log_file = None
    logger = None
    db_manager = None


# 全局变量用于信号处理
_server = None
_dashboard_server = None

# 配置目录
CONFIG_DIR = os.path.expanduser('~/.http-proxy')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
SERVICE_NAME = 'http-proxy'
SERVICE_FILE = os.path.expanduser(f'~/.config/systemd/user/{SERVICE_NAME}.service')


def signal_handler(signum, frame):
    """信号处理器"""
    global _server, _dashboard_server
    # shutdown() 必须在不同线程中调用
    def do_shutdown():
        if _server:
            _server.shutdown()
        if _dashboard_server:
            _dashboard_server.shutdown()
    threading.Thread(target=do_shutdown, daemon=True).start()


def save_config(args):
    """保存配置到文件（只保存非默认值）"""
    import json

    # 默认值
    DEFAULTS = {
        'port': 12345,
        'no_web': False,
        'web_host': '127.0.0.1',
        'web_port': 3420,
        'enable_log_file': False,
        'no_color': False,
        'connect_timeout': 60,
        'stream_timeout': 300,
        'verify_ssl': False,
        'web_auth_token': None
    }

    # 只保存非默认值
    config = {}

    if args.port != DEFAULTS['port']:
        config['port'] = args.port
    if args.no_web != DEFAULTS['no_web']:
        config['no_web'] = args.no_web
    if args.web_host != DEFAULTS['web_host']:
        config['web_host'] = args.web_host
    if args.web_port != DEFAULTS['web_port']:
        config['web_port'] = args.web_port
    if args.enable_log_file != DEFAULTS['enable_log_file']:
        config['enable_log_file'] = args.enable_log_file
    if args.no_color != DEFAULTS['no_color']:
        config['no_color'] = args.no_color
    if args.connect_timeout != DEFAULTS['connect_timeout']:
        config['connect_timeout'] = args.connect_timeout
    if args.stream_timeout != DEFAULTS['stream_timeout']:
        config['stream_timeout'] = args.stream_timeout
    if args.verify_ssl != DEFAULTS['verify_ssl']:
        config['verify_ssl'] = args.verify_ssl
    if args.web_auth_token != DEFAULTS['web_auth_token']:
        config['web_auth_token'] = args.web_auth_token

    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def load_config():
    """从文件加载配置"""
    import json
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None


def get_script_path():
    """获取脚本绝对路径"""
    return os.path.abspath(__file__)


def get_working_dir():
    """获取工作目录"""
    return os.path.dirname(os.path.abspath(__file__))


def install_service():
    """安装 systemd 用户服务"""
    import json

    # 读取配置文件，如果不存在则创建空配置文件
    config = load_config()
    if config is None:
        config = {}
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"{Colors.GREEN}✓{Colors.RESET} 已创建配置文件: {CONFIG_FILE}")

    script_path = get_script_path()
    working_dir = get_working_dir()
    python_path = sys.executable

    # 构建启动命令（配置中只保存非默认值，存在的就需要添加）
    cmd_args = [python_path, script_path]

    if 'port' in config:
        cmd_args.append(f'--port={config["port"]}')

    if config.get('enable_log_file'):
        cmd_args.append('--enable-log-file')

    if config.get('no_web'):
        cmd_args.append('--no-web')
    else:
        if 'web_host' in config:
            cmd_args.append(f'--web-host={config["web_host"]}')
        if 'web_port' in config:
            cmd_args.append(f'--web-port={config["web_port"]}')

    if 'connect_timeout' in config:
        cmd_args.append(f'--connect-timeout={config["connect_timeout"]}')

    if 'stream_timeout' in config:
        cmd_args.append(f'--stream-timeout={config["stream_timeout"]}')

    if config.get('verify_ssl'):
        cmd_args.append('--verify-ssl')

    if 'web_auth_token' in config:
        cmd_args.append(f'--web-auth-token={config["web_auth_token"]}')

    # 构建 systemd 用户服务文件
    service_content = f"""[Unit]
Description=HTTP Proxy Logger
After=network.target

[Service]
Type=simple
WorkingDirectory={working_dir}
ExecStart={' '.join(cmd_args)}
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""

    # 写入服务文件
    try:
        service_dir = os.path.dirname(SERVICE_FILE)
        os.makedirs(service_dir, exist_ok=True)

        with open(SERVICE_FILE, 'w') as f:
            f.write(service_content)
        print(f"{Colors.GREEN}✓{Colors.RESET} 服务文件已创建: {SERVICE_FILE}")

        # 重载 systemd 用户服务
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
        print(f"{Colors.GREEN}✓{Colors.RESET} systemd 配置已重载")

        # 启用服务
        subprocess.run(['systemctl', '--user', 'enable', SERVICE_NAME], check=True)
        print(f"{Colors.GREEN}✓{Colors.RESET} 服务已设置为开机自启")

        # 启动服务
        subprocess.run(['systemctl', '--user', 'start', SERVICE_NAME], check=True)
        print(f"{Colors.GREEN}✓{Colors.RESET} 服务已启动")

        print(f"\n{Colors.CYAN}服务管理命令:{Colors.RESET}")
        print(f"  查看状态: systemctl --user status {SERVICE_NAME}")
        print(f"  查看日志: journalctl --user -u {SERVICE_NAME} -f")
        print(f"  停止服务: systemctl --user stop {SERVICE_NAME}")
        print(f"  卸载服务: python {script_path} uninstall")

        return True

    except subprocess.CalledProcessError as e:
        print(f"{Colors.RED}安装失败: {e}{Colors.RESET}")
        return False
    except Exception as e:
        print(f"{Colors.RED}安装失败: {e}{Colors.RESET}")
        return False


def uninstall_service():
    """卸载 systemd 用户服务"""
    try:
        # 停止服务
        result = subprocess.run(['systemctl', '--user', 'is-active', SERVICE_NAME],
                                capture_output=True, text=True)
        if result.returncode == 0:
            subprocess.run(['systemctl', '--user', 'stop', SERVICE_NAME], check=True)
            print(f"{Colors.GREEN}✓{Colors.RESET} 服务已停止")

        # 禁用服务
        result = subprocess.run(['systemctl', '--user', 'is-enabled', SERVICE_NAME],
                                capture_output=True, text=True)
        if result.returncode == 0:
            subprocess.run(['systemctl', '--user', 'disable', SERVICE_NAME], check=True)
            print(f"{Colors.GREEN}✓{Colors.RESET} 已取消开机自启")

        # 删除服务文件
        if os.path.exists(SERVICE_FILE):
            os.remove(SERVICE_FILE)
            print(f"{Colors.GREEN}✓{Colors.RESET} 服务文件已删除")

        # 重载 systemd
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
        print(f"{Colors.GREEN}✓{Colors.RESET} systemd 配置已重载")

        print(f"\n{Colors.GREEN}服务已完全卸载{Colors.RESET}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"{Colors.YELLOW}警告: {e}{Colors.RESET}")
        # 继续尝试删除文件
        if os.path.exists(SERVICE_FILE):
            os.remove(SERVICE_FILE)
            print(f"{Colors.GREEN}✓{Colors.RESET} 服务文件已删除")
        return True
    except Exception as e:
        print(f"{Colors.RED}卸载失败: {e}{Colors.RESET}")
        return False


def run_server(args):
    """运行服务器"""
    global _server, _dashboard_server

    # 创建数据库管理器
    db_manager = DatabaseManager(args.db_file)

    # 创建日志记录器
    logger = RequestLogger(args.log_file, db_manager, enable_file_log=args.enable_log_file)

    # 启动 Dashboard 服务器（独立线程）
    if not args.no_web:
        from dashboard.handler import DashboardHandler
        _dashboard_server = DashboardServer((args.web_host, args.web_port), DashboardHandler)
        _dashboard_server.db_manager = db_manager
        _dashboard_server.auth_token = args.web_auth_token
        dashboard_thread = threading.Thread(target=_dashboard_server.serve_forever, daemon=True)
        dashboard_thread.start()

    # 启动代理服务器
    _server = ThreadedTCPServer(('0.0.0.0', args.port), ForwardingHandler)
    _server.log_file = args.log_file
    _server.logger = logger
    _server.db_manager = db_manager
    _server.connect_timeout = args.connect_timeout
    _server.stream_timeout = args.stream_timeout
    _server.verify_ssl = args.verify_ssl

    print(f"\n{Colors.BOLD}{Colors.CYAN}HTTP Forwarding Server{Colors.RESET}")
    print(f"{Colors.GREEN}✓{Colors.RESET} 代理服务器已启动 (PID: {os.getpid()})")
    print(f"{Colors.BLUE}→{Colors.RESET} 代理端口: {Colors.YELLOW}{args.port}{Colors.RESET}")
    if args.enable_log_file:
        print(f"{Colors.BLUE}→{Colors.RESET} 日志文件: {Colors.YELLOW}{args.log_file}{Colors.RESET}")
    print(f"{Colors.BLUE}→{Colors.RESET} 数据库: {Colors.YELLOW}{args.db_file}{Colors.RESET}")
    if args.verify_ssl:
        print(f"{Colors.BLUE}→{Colors.RESET} SSL验证: {Colors.GREEN}已启用{Colors.RESET}")
    else:
        print(f"{Colors.BLUE}→{Colors.RESET} SSL验证: {Colors.YELLOW}已禁用{Colors.RESET}")

    if not args.no_web:
        print(f"\n{Colors.BOLD}{Colors.CYAN}Dashboard{Colors.RESET}")
        print(f"{Colors.GREEN}✓{Colors.RESET} 看板服务器已启动")
        print(f"{Colors.BLUE}→{Colors.RESET} 访问地址: {Colors.YELLOW}http://{args.web_host if args.web_host != '0.0.0.0' else '127.0.0.1'}:{args.web_port}{Colors.RESET}")
        if args.web_auth_token:
            print(f"{Colors.BLUE}→{Colors.RESET} 认证令牌: {Colors.YELLOW}{args.web_auth_token}{Colors.RESET}")
        else:
            print(f"{Colors.BLUE}→{Colors.RESET} 认证: {Colors.YELLOW}无认证{Colors.RESET}")
    print(f"\n{Colors.BOLD}使用方式:{Colors.RESET}")
    print(f"  {Colors.DIM}http://127.0.0.1:{args.port}/http://example.com{Colors.RESET}")
    print(f"  {Colors.DIM}http://127.0.0.1:{args.port}/https://example.com{Colors.RESET}")
    print(f"\n{Colors.DIM}按 Ctrl+C 停止服务{Colors.RESET}\n")

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
    except KeyboardInterrupt:
        pass
    finally:
        print(f"\n{Colors.YELLOW}服务已关闭{Colors.RESET}")
        _server.server_close()
        if _dashboard_server:
            _dashboard_server.server_close()


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
  install     安装 Linux 用户服务（开机自启）
  uninstall   卸载 Linux 用户服务

示例:
  %(prog)s                           # 前台启动服务
  %(prog)s install                   # 安装系统服务
  %(prog)s uninstall                 # 卸载系统服务
  %(prog)s -p 8080                   # 指定端口启动
        """
    )
    parser.add_argument(
        'command',
        nargs='?',
        default=None,
        choices=['install', 'uninstall'],
        help='命令: install(安装服务), uninstall(卸载服务)'
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
        default=None,
        help='日志文件路径 (默认: ~/.http-proxy/logs/proxy.log)'
    )
    parser.add_argument(
        '--enable-log-file',
        action='store_true',
        help='启用日志文件输出 (默认: 关闭)'
    )
    parser.add_argument(
        '--db-file',
        default=None,
        help='数据库文件路径 (默认: ~/.http-proxy/data/proxy.db)'
    )
    parser.add_argument(
        '--connect-timeout',
        type=int,
        default=60,
        help='连接超时时间（秒）(默认: 60)'
    )
    parser.add_argument(
        '--stream-timeout',
        type=int,
        default=300,
        help='流式响应超时时间（秒）(默认: 300)'
    )
    parser.add_argument(
        '--verify-ssl',
        action='store_true',
        help='启用 SSL 证书验证 (默认: 关闭，接受所有证书)'
    )
    parser.add_argument(
        '--web-auth-token',
        default=None,
        help='Dashboard API 认证令牌 (默认: 无认证)'
    )

    args = parser.parse_args()

    # 设置默认数据目录
    default_dir = os.path.expanduser('~/.http-proxy')
    if args.db_file is None:
        args.db_file = os.path.join(default_dir, 'data/proxy.db')
    if args.log_file is None:
        args.log_file = os.path.join(default_dir, 'logs/proxy.log')

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
    if args.command == 'install':
        install_service()

    elif args.command == 'uninstall':
        uninstall_service()

    else:
        # 保存配置
        save_config(args)

        # 设置信号处理
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        # 前台运行
        run_server(args)


if __name__ == '__main__':
    main()