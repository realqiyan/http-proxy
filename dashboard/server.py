"""Dashboard 服务器"""

import socketserver
import threading

from .handler import DashboardHandler
from utils.colors import Colors


class DashboardServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Dashboard Web 服务器"""
    allow_reuse_address = True
    daemon_threads = True
    db_manager = None


def start_dashboard_server(host: str, port: int, db_manager):
    """启动 Dashboard 服务器"""
    try:
        server = DashboardServer((host, port), DashboardHandler)
        server.db_manager = db_manager
        server.serve_forever()
    except Exception as e:
        print(f"{Colors.RED}Dashboard server error: {e}{Colors.RESET}")