"""数据库管理模块"""

import sqlite3
import threading
import uuid
import gzip
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class DatabaseManager:
    """SQLite 数据库管理器，用于持久化存储请求/响应数据"""

    def __init__(self, db_path: str = 'data/proxy.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 主请求表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    method TEXT NOT NULL,
                    url TEXT NOT NULL,
                    host TEXT,
                    path TEXT,
                    status INTEGER,
                    duration_ms REAL,
                    request_size INTEGER DEFAULT 0,
                    response_size INTEGER DEFAULT 0,
                    is_streaming INTEGER DEFAULT 0,
                    error TEXT
                )
            ''')

            # 请求详情表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS request_details (
                    request_id TEXT PRIMARY KEY,
                    request_headers TEXT,
                    request_body TEXT,
                    response_headers TEXT,
                    response_body TEXT,
                    FOREIGN KEY (request_id) REFERENCES requests(id)
                )
            ''')

            # 创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_method ON requests(method)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status)')

            conn.commit()

    def save_request(
        self,
        method: str,
        url: str,
        request_headers: Dict[str, str],
        request_body: bytes,
        response_status: int,
        response_reason: str,
        response_headers: list,
        response_body: bytes,
        duration: float,
        is_streaming: bool = False,
        error: str = None
    ) -> str:
        """保存请求/响应数据到数据库"""
        request_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()

        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query

        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 保存主记录
                cursor.execute('''
                    INSERT INTO requests (id, timestamp, method, url, host, path, status, duration_ms,
                                         request_size, response_size, is_streaming, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    request_id, timestamp, method, url, host, path,
                    response_status, duration * 1000,
                    len(request_body) if request_body else 0,
                    len(response_body) if response_body else 0,
                    1 if is_streaming else 0,
                    error
                ))

                # 保存详情（压缩大文本）
                req_headers_json = json.dumps(request_headers, ensure_ascii=False) if request_headers else '{}'
                req_body_str = self._encode_body(request_body, request_headers.get('Content-Type', ''))
                resp_headers_json = json.dumps(dict(response_headers), ensure_ascii=False) if response_headers else '{}'
                resp_body_str = self._encode_body(response_body, dict(response_headers).get('Content-Type', ''))

                cursor.execute('''
                    INSERT INTO request_details (request_id, request_headers, request_body,
                                                response_headers, response_body)
                    VALUES (?, ?, ?, ?, ?)
                ''', (request_id, req_headers_json, req_body_str, resp_headers_json, resp_body_str))

                conn.commit()

        return request_id

    def _encode_body(self, body: bytes, content_type: str = '') -> str:
        """编码 body 为可存储的字符串"""
        if not body:
            return ''

        # 尝试解码为文本
        try:
            text = body.decode('utf-8')
            # 如果太大，尝试压缩
            if len(text) > 100000:  # 100KB 以上压缩
                import base64
                compressed = gzip.compress(text.encode('utf-8'))
                return 'GZIP:' + base64.b64encode(compressed).decode('ascii')
            return text
        except UnicodeDecodeError:
            # 二进制数据用 base64
            import base64
            return 'BASE64:' + base64.b64encode(body).decode('ascii')

    def get_requests(self, limit: int = 100, offset: int = 0,
                     method: str = None, status: str = None, search: str = None) -> List[Dict]:
        """获取请求列表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = 'SELECT * FROM requests WHERE 1=1'
            params = []

            if method:
                query += ' AND method = ?'
                params.append(method)

            if status:
                if status == '2xx':
                    query += ' AND status >= 200 AND status < 300'
                elif status == '3xx':
                    query += ' AND status >= 300 AND status < 400'
                elif status == '4xx':
                    query += ' AND status >= 400 AND status < 500'
                elif status == '5xx':
                    query += ' AND status >= 500'

            if search:
                query += ' AND (url LIKE ? OR host LIKE ? OR path LIKE ?)'
                params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])

            query += ' ORDER BY timestamp DESC LIMIT ? OFFSET ?'
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [dict(row) for row in rows]

    def get_request_detail(self, request_id: str) -> Optional[Dict]:
        """获取请求详情"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT r.*, d.request_headers, d.request_body, d.response_headers, d.response_body
                FROM requests r
                LEFT JOIN request_details d ON r.id = d.request_id
                WHERE r.id = ?
            ''', (request_id,))

            row = cursor.fetchone()
            if row:
                result = dict(row)
                # 解码 body
                result['request_body'] = self._decode_body(result.get('request_body', ''))
                result['response_body'] = self._decode_body(result.get('response_body', ''))
                return result
            return None

    def _decode_body(self, body_str: str) -> str:
        """解码存储的 body"""
        if not body_str:
            return ''

        if body_str.startswith('GZIP:'):
            import base64
            try:
                compressed = base64.b64decode(body_str[5:].encode('ascii'))
                return gzip.decompress(compressed).decode('utf-8')
            except:
                return body_str
        elif body_str.startswith('BASE64:'):
            import base64
            return f"(binary data: {len(base64.b64decode(body_str[7:]))} bytes)"

        return body_str

    def get_stats(self) -> Dict:
        """获取统计信息"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) FROM requests')
            total = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) FROM requests WHERE status >= 200 AND status < 300')
            success = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) FROM requests WHERE status >= 400')
            errors = cursor.fetchone()[0]

            cursor.execute('SELECT AVG(duration_ms) FROM requests')
            avg_duration = cursor.fetchone()[0] or 0

            return {
                'total': total,
                'success': success,
                'errors': errors,
                'avg_duration': round(avg_duration, 2)
            }

    def clear_old_requests(self, days: int = 7):
        """清理旧请求"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM request_details WHERE request_id IN (SELECT id FROM requests WHERE timestamp < ?)', (cutoff,))
                cursor.execute('DELETE FROM requests WHERE timestamp < ?', (cutoff,))
                conn.commit()

    def clear_requests_by_range(self, start_time: str = None, end_time: str = None) -> int:
        """
        按时间区间清理请求数据

        参数:
            start_time: 开始时间 (ISO格式: 2024-01-01T00:00:00 或 2024-01-01)
            end_time: 结束时间 (ISO格式: 2024-01-31T23:59:59 或 2024-01-31)

        返回:
            删除的记录数
        """
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 处理日期格式
                if start_time and len(start_time) == 10:
                    start_time = f"{start_time}T00:00:00"
                if end_time and len(end_time) == 10:
                    end_time = f"{end_time}T23:59:59"

                query = 'DELETE FROM requests WHERE 1=1'
                params = []

                if start_time:
                    query += ' AND timestamp >= ?'
                    params.append(start_time)

                if end_time:
                    query += ' AND timestamp <= ?'
                    params.append(end_time)

                # 先删除详情
                detail_query = f'DELETE FROM request_details WHERE request_id IN (SELECT id FROM requests WHERE 1=1'
                detail_params = []
                if start_time:
                    detail_query += ' AND timestamp >= ?'
                    detail_params.append(start_time)
                if end_time:
                    detail_query += ' AND timestamp <= ?'
                    detail_params.append(end_time)
                detail_query += ')'

                cursor.execute(detail_query, detail_params)
                cursor.execute(query, params)
                deleted = cursor.rowcount
                conn.commit()

                return deleted