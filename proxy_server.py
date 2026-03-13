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
- Linux systemd 服务支持
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
import shutil
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

# 配置目录
CONFIG_DIR = os.path.expanduser('~/.http-proxy')
PID_FILE = os.path.join(CONFIG_DIR, 'proxy.pid')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
SERVICE_NAME = 'http-proxy'
SERVICE_FILE = f'/etc/systemd/system/{SERVICE_NAME}.service'


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


def save_config(args):
    """保存配置到文件"""
    import json
    config = {
        'port': args.port,
        'no_web': args.no_web,
        'web_host': args.web_host,
        'web_port': args.web_port,
        'enable_log_file': args.enable_log_file,
        'log_file': args.log_file,
        'db_file': args.db_file,
        'restart_delay': args.restart_delay,
        'no_color': args.no_color
    }
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


def get_script_path():
    """获取脚本绝对路径"""
    return os.path.abspath(__file__)


def get_working_dir():
    """获取工作目录"""
    return os.path.dirname(os.path.abspath(__file__))


def install_service():
    """安装 systemd 服务"""
    # 先检查配置文件是否存在
    config = load_config()
    if not config:
        print(f"{Colors.RED}错误: 配置文件不存在，请先启动一次服务{Colors.RESET}")
        print(f"{Colors.YELLOW}提示: python proxy_server.py{Colors.RESET}")
        return False

    # 检查是否有 root 权限
    if os.geteuid() != 0:
        print(f"{Colors.RED}错误: 需要 root 权限，请使用 sudo{Colors.RESET}")
        return False

    script_path = get_script_path()
    working_dir = get_working_dir()
    python_path = sys.executable

    # 构建启动命令（从配置读取）
    cmd_args = [python_path, script_path, 'start']
    if config.get('enable_log_file'):
        cmd_args.append('--enable-log-file')
    if config.get('log_file'):
        cmd_args.append(f'--log-file={config["log_file"]}')
    if config.get('db_file'):
        cmd_args.append(f'--db-file={config["db_file"]}')
    if config.get('port'):
        cmd_args.append(f'--port={config["port"]}')
    if config.get('no_web'):
        cmd_args.append('--no-web')
    else:
        if config.get('web_host'):
            cmd_args.append(f'--web-host={config["web_host"]}')
        if config.get('web_port'):
            cmd_args.append(f'--web-port={config["web_port"]}')
    if config.get('restart_delay'):
        cmd_args.append(f'--restart-delay={config["restart_delay"]}')

    # 构建 systemd 服务文件
    service_content = f"""[Unit]
Description=HTTP Proxy Logger
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={working_dir}
ExecStart={' '.join(cmd_args)}
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

    # 写入服务文件
    try:
        with open(SERVICE_FILE, 'w') as f:
            f.write(service_content)
        print(f"{Colors.GREEN}✓{Colors.RESET} 服务文件已创建: {SERVICE_FILE}")

        # 重载 systemd
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        print(f"{Colors.GREEN}✓{Colors.RESET} systemd 配置已重载")

        # 启用服务
        subprocess.run(['systemctl', 'enable', SERVICE_NAME], check=True)
        print(f"{Colors.GREEN}✓{Colors.RESET} 服务已设置为开机自启")

        # 启动服务
        subprocess.run(['systemctl', 'start', SERVICE_NAME], check=True)
        print(f"{Colors.GREEN}✓{Colors.RESET} 服务已启动")

        print(f"\n{Colors.CYAN}服务管理命令:{Colors.RESET}")
        print(f"  查看状态: sudo systemctl status {SERVICE_NAME}")
        print(f"  查看日志: sudo journalctl -u {SERVICE_NAME} -f")
        print(f"  停止服务: sudo systemctl stop {SERVICE_NAME}")
        print(f"  卸载服务: sudo python {script_path} uninstall")

        return True

    except subprocess.CalledProcessError as e:
        print(f"{Colors.RED}安装失败: {e}{Colors.RESET}")
        return False
    except Exception as e:
        print(f"{Colors.RED}安装失败: {e}{Colors.RESET}")
        return False


def uninstall_service():
    """卸载 systemd 服务"""
    # 检查是否有 root 权限
    if os.geteuid() != 0:
        print(f"{Colors.RED}错误: 需要 root 权限，请使用 sudo{Colors.RESET}")
        return False

    try:
        # 停止服务
        result = subprocess.run(['systemctl', 'is-active', SERVICE_NAME],
                                capture_output=True, text=True)
        if result.returncode == 0:
            subprocess.run(['systemctl', 'stop', SERVICE_NAME], check=True)
            print(f"{Colors.GREEN}✓{Colors.RESET} 服务已停止")

        # 禁用服务
        result = subprocess.run(['systemctl', 'is-enabled', SERVICE_NAME],
                                capture_output=True, text=True)
        if result.returncode == 0:
            subprocess.run(['systemctl', 'disable', SERVICE_NAME], check=True)
            print(f"{Colors.GREEN}✓{Colors.RESET} 已取消开机自启")

        # 删除服务文件
        if os.path.exists(SERVICE_FILE):
            os.remove(SERVICE_FILE)
            print(f"{Colors.GREEN}✓{Colors.RESET} 服务文件已删除")

        # 重载 systemd
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
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
        except OSError as e:
            # 端口占用等错误不重试
            if e.errno == 98:  # Address already in use
                print(f"\n{Colors.RED}[Daemon] 端口 {args.port} 已被占用，无法启动{Colors.RESET}")
                remove_pid()
                sys.exit(1)
            raise
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

    # 保存配置
    save_config(args)

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
  start       启动服务（后台运行，自动重启）
  stop        停止服务
  status      查看服务状态
  install     安装 Linux 系统服务（开机自启）
  uninstall   卸载 Linux 系统服务

示例:
  %(prog)s                           # 启动服务（后台）
  %(prog)s stop                      # 停止服务
  %(prog)s status                    # 查看状态
  %(prog)s install                   # 安装系统服务
  %(prog)s uninstall                 # 卸载系统服务
  %(prog)s -p 8080                   # 指定端口启动
        """
    )
    parser.add_argument(
        'command',
        nargs='?',
        default='start',
        choices=['start', 'stop', 'status', 'install', 'uninstall'],
        help='命令: start(启动), stop(停止), status(状态), install(安装服务), uninstall(卸载服务)'
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
        '--restart-delay',
        type=int,
        default=3,
        help='自动重启延迟秒数 (默认: 3)'
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

    elif args.command == 'install':
        install_service()

    elif args.command == 'uninstall':
        uninstall_service()


if __name__ == '__main__':
    main()