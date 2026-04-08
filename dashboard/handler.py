"""Dashboard 请求处理器"""

import http.server
import json

from .templates import DASHBOARD_HTML


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """Dashboard Web 界面处理器"""

    def log_message(self, format, *args):
        pass

    def _check_auth(self) -> bool:
        """检查认证令牌，返回是否通过"""
        auth_token = getattr(self.server, 'auth_token', None)
        if auth_token is None:
            return True  # 未配置认证令牌，允许访问

        # 从 Authorization 头获取令牌
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            if token == auth_token:
                return True

        # 从查询参数获取令牌
        from urllib.parse import parse_qs
        params = parse_qs(self.path.split('?')[1] if '?' in self.path else '')
        token = params.get('token', [None])[0]
        if token == auth_token:
            return True

        return False

    def _send_auth_error(self):
        """发送认证失败响应"""
        self.send_response(401)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'error': 'Unauthorized', 'message': '需要认证令牌'}).encode('utf-8'))

    def do_GET(self):
        # 获取路径部分（去掉查询字符串）
        path_only = self.path.split('?')[0]

        if path_only == '/' or path_only == '/index.html':
            # 静态页面不需要认证
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode('utf-8'))

        elif path_only == '/api/requests':
            if not self._check_auth():
                self._send_auth_error()
                return
            self._handle_api_requests()

        elif path_only.startswith('/api/requests/'):
            if not self._check_auth():
                self._send_auth_error()
                return
            request_id = path_only.split('/')[-1]
            self._handle_api_request_detail(request_id)

        elif path_only == '/api/stats':
            if not self._check_auth():
                self._send_auth_error()
                return
            self._handle_api_stats()

        elif path_only == '/api/clear':
            if not self._check_auth():
                self._send_auth_error()
                return
            self._handle_api_clear()

        else:
            self.send_error(404)

    def _handle_api_requests(self):
        from urllib.parse import parse_qs
        params = parse_qs(self.path.split('?')[1] if '?' in self.path else '')

        limit = int(params.get('limit', [100])[0])
        method = params.get('method', [None])[0]
        status = params.get('status', [None])[0]
        search = params.get('search', [None])[0]

        db = self.server.db_manager
        requests = db.get_requests(limit=limit, method=method, status=status, search=search)

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(requests).encode('utf-8'))

    def _handle_api_request_detail(self, request_id: str):
        db = self.server.db_manager
        detail = db.get_request_detail(request_id)

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(detail).encode('utf-8'))

    def _handle_api_stats(self):
        db = self.server.db_manager
        stats = db.get_stats()

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(stats).encode('utf-8'))

    def do_DELETE(self):
        if not self._check_auth():
            self._send_auth_error()
            return
        path_only = self.path.split('?')[0]
        if path_only == '/api/requests':
            self._handle_api_clear()
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.end_headers()

    def _handle_api_clear(self):
        from urllib.parse import parse_qs
        params = parse_qs(self.path.split('?')[1] if '?' in self.path else '')

        start_time = params.get('start', [None])[0]
        end_time = params.get('end', [None])[0]
        days = params.get('days', [None])[0]

        db = self.server.db_manager

        if days:
            # 按天数清理旧数据
            try:
                days_int = int(days)
                db.clear_old_requests(days=days_int)
                result = {'success': True, 'message': f'已清理 {days_int} 天前的数据'}
            except ValueError:
                result = {'success': False, 'error': 'days 参数必须是整数'}
        elif start_time or end_time:
            # 按时间区间清理
            deleted = db.clear_requests_by_range(start_time, end_time)
            result = {'success': True, 'deleted': deleted, 'message': f'已删除 {deleted} 条记录'}
        else:
            result = {'success': False, 'error': '请提供 start/end 或 days 参数'}

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(result).encode('utf-8'))