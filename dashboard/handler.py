"""Dashboard 请求处理器"""

import http.server
import json

from .templates import DASHBOARD_HTML


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """Dashboard Web 界面处理器"""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        # 获取路径部分（去掉查询字符串）
        path_only = self.path.split('?')[0]

        if path_only == '/' or path_only == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode('utf-8'))

        elif path_only == '/api/requests':
            self._handle_api_requests()

        elif path_only.startswith('/api/requests/'):
            request_id = path_only.split('/')[-1]
            self._handle_api_request_detail(request_id)

        elif path_only == '/api/stats':
            self._handle_api_stats()

        elif path_only == '/api/clear':
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
        path_only = self.path.split('?')[0]
        if path_only == '/api/requests':
            self._handle_api_clear()
        else:
            self.send_error(404)

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