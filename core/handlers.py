"""HTTP 代理处理器"""

import http.server
import http.client
import ssl
import socket
import re
import time
from io import BytesIO
from urllib.parse import urlparse
from datetime import datetime
from typing import Optional, Tuple, Dict

from utils.colors import Colors
from utils.format import format_size, format_duration


class ForwardingHandler(http.server.BaseHTTPRequestHandler):
    """HTTP 转发请求处理器"""

    protocol_version = 'HTTP/1.1'
    timeout = 60  # 连接超时时间

    def setup(self):
        """初始化连接"""
        self.request.settimeout(self.timeout)
        super().setup()

    def log_message(self, format, *args):
        """禁用默认日志"""
        pass

    def _parse_target_url(self) -> Optional[Tuple[str, str, int, str]]:
        """
        从请求路径解析目标 URL

        返回: (scheme, host, port, path) 或 None
        """
        path = self.path
        match = re.match(r'^/(https?://)(.*)$', path)
        if not match:
            return None

        scheme_prefix = match.group(1)
        rest = match.group(2)
        full_url = scheme_prefix + rest
        parsed = urlparse(full_url)

        if not parsed.hostname:
            return None

        scheme = parsed.scheme
        host = parsed.hostname
        port = parsed.port or (443 if scheme == 'https' else 80)

        target_path = parsed.path or '/'
        if parsed.query:
            target_path += '?' + parsed.query
        if parsed.fragment:
            target_path += '#' + parsed.fragment

        return scheme, host, port, target_path

    def _is_streaming_response(self, headers: Dict[str, str]) -> bool:
        """检测是否为流式响应"""
        content_type = headers.get('Content-Type', '').lower()
        transfer_encoding = headers.get('Transfer-Encoding', '').lower()

        # SSE (Server-Sent Events)
        if 'text/event-stream' in content_type:
            return True

        # Chunked encoding 且可能是流式
        if 'chunked' in transfer_encoding:
            streaming_types = ['text/event-stream', 'application/x-ndjson', 'application/stream+json']
            if any(t in content_type for t in streaming_types):
                return True

        return False

    def _handle_streaming_response(self, response, status: int, reason: str, headers: list) -> bytes:
        """处理流式响应，边读边转发，同时缓存部分内容用于日志"""
        # 发送响应头
        self.send_response(status, reason)

        for key, value in headers:
            if key.lower() not in ('connection',):
                self.send_header(key, value)

        self.end_headers()

        # 缓存前 64KB 用于日志
        cached_body = BytesIO()
        cache_limit = 65536
        total_size = 0

        try:
            # 逐块读取并转发
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break

                # 转发给客户端
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break

                # 缓存用于日志
                if cached_body.tell() < cache_limit:
                    remaining = cache_limit - cached_body.tell()
                    cached_body.write(chunk[:remaining])

                total_size += len(chunk)

        except Exception as e:
            print(f"{Colors.YELLOW}[STREAMING] Error: {e}{Colors.RESET}")

        # 返回缓存的响应体（可能被截断）
        result = cached_body.getvalue()
        if total_size > cache_limit:
            result += f"\n\n... (truncated, total {format_size(total_size)})".encode('utf-8')

        return result

    def _handle_request(self, method: str):
        """处理请求并转发"""
        start_time = time.time()

        # 解析目标 URL
        target = self._parse_target_url()
        if not target:
            self.send_error(400, 'Bad Request: Invalid URL format. Use /http://example.com/path')
            return

        scheme, host, port, target_path = target
        full_url = f"{scheme}://{host}:{port}{target_path}"

        conn = None
        try:
            # ===== 收集请求信息 =====
            request_headers = {}
            for key, value in self.headers.items():
                request_headers[key] = value

            # 读取请求体
            content_length = int(self.headers.get('Content-Length', 0))
            request_body = self.rfile.read(content_length) if content_length > 0 else b''

            # 创建目标连接（增加超时和重试）
            max_retries = 3
            retry_count = 0
            last_error = None

            while retry_count < max_retries:
                try:
                    if scheme == 'https':
                        context = ssl.create_default_context()
                        context.check_hostname = False
                        context.verify_mode = ssl.CERT_NONE
                        conn = http.client.HTTPSConnection(host, port, context=context, timeout=60)
                    else:
                        conn = http.client.HTTPConnection(host, port, timeout=60)

                    # 准备转发的请求头
                    forward_headers = {}
                    for key, value in self.headers.items():
                        if key.lower() not in ('connection', 'keep-alive', 'proxy-authenticate',
                                               'proxy-authorization', 'te', 'trailers',
                                               'transfer-encoding', 'upgrade', 'host'):
                            forward_headers[key] = value

                    forward_headers['Connection'] = 'close'

                    # 发送请求到目标服务器
                    conn.request(method, target_path, body=request_body, headers=forward_headers)

                    # 获取响应
                    response = conn.getresponse()
                    break

                except (http.client.HTTPException, socket.timeout, socket.error, ConnectionError, OSError) as e:
                    last_error = e
                    retry_count += 1
                    if conn:
                        try:
                            conn.close()
                        except:
                            pass
                    if retry_count < max_retries:
                        time.sleep(0.5 * retry_count)
                    continue

            if retry_count >= max_retries:
                raise last_error or Exception("Connection failed after retries")

            # ===== 收集响应信息 =====
            response_status = response.status
            response_reason = response.reason
            response_headers = response.getheaders()
            headers_dict = dict(response_headers)

            # 检测是否为流式响应
            is_streaming = self._is_streaming_response(headers_dict)

            if is_streaming:
                # 流式响应处理
                response_body = self._handle_streaming_response(response, response_status, response_reason, response_headers)
            else:
                # 普通响应：读取完整响应体
                response_body = response.read()

                # ===== 发送响应给客户端 =====
                self.send_response(response_status, response_reason)

                for key, value in response_headers:
                    if key.lower() not in ('transfer-encoding', 'connection'):
                        self.send_header(key, value)

                self.send_header('Content-Length', str(len(response_body)))
                self.end_headers()

                self.wfile.write(response_body)

            # ===== 记录日志 =====
            duration = time.time() - start_time

            if hasattr(self.server, 'logger') and self.server.logger:
                self.server.logger.log_request_response(
                    method=method,
                    url=full_url,
                    request_headers=request_headers,
                    request_body=request_body,
                    response_status=response_status,
                    response_reason=response_reason,
                    response_headers=response_headers,
                    response_body=response_body,
                    duration=duration,
                    is_streaming=is_streaming
                )

            # 终端简短输出
            size = len(response_body) if response_body else 0
            self._log_terminal(method, full_url, response_status, size, duration, is_streaming)

        except http.client.HTTPException as e:
            self._log_error(method, full_url, str(e))
            if not self.headers_sent:
                self.send_error(502, f'Bad Gateway: {e}')
        except socket.timeout as e:
            self._log_error(method, full_url, f'Connection timeout: {e}')
            if not self.headers_sent:
                self.send_error(504, f'Gateway Timeout: {e}')
        except (socket.error, ConnectionError, OSError) as e:
            self._log_error(method, full_url, f'Connection error: {e}')
            if not self.headers_sent:
                self.send_error(502, f'Bad Gateway: Connection failed - {e}')
        except Exception as e:
            self._log_error(method, full_url, str(e))
            if not self.headers_sent:
                self.send_error(500, f'Internal Error: {e}')
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass

    def _log_terminal(self, method: str, url: str, status: int, size: int, duration: float, is_streaming: bool = False):
        """终端简短输出"""
        if status < 300:
            status_color = Colors.GREEN
        elif status < 400:
            status_color = Colors.YELLOW
        else:
            status_color = Colors.RED

        streaming_tag = f"{Colors.YELLOW}[STREAMING]{Colors.RESET} " if is_streaming else ""

        log_msg = (
            f"{Colors.CYAN}{method}{Colors.RESET} "
            f"{url} "
            f"{status_color}{status}{Colors.RESET} "
            f"{Colors.MAGENTA}{format_size(size)}{Colors.RESET} "
            f"{Colors.BLUE}{format_duration(duration)}{Colors.RESET}"
        )
        print(f"{Colors.DIM}{datetime.now().strftime('%H:%M:%S')}{Colors.RESET} {streaming_tag}{log_msg}")

    def _log_error(self, method: str, url: str, error: str):
        """记录错误日志"""
        print(f"{Colors.DIM}{datetime.now().strftime('%H:%M:%S')}{Colors.RESET} "
              f"{Colors.RED}[ERROR]{Colors.RESET} {method} {url} - {error}")

        if hasattr(self.server, 'logger') and self.server.logger and self.server.logger.enable_file_log:
            with open(self.server.logger.log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'═'*60}\n")
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR\n")
                f.write(f"{'─'*60}\n")
                f.write(f"{method} {url}\n")
                f.write(f"Error: {error}\n")
                f.write(f"{'═'*60}\n\n")

    def do_GET(self):
        self._handle_request('GET')

    def do_POST(self):
        self._handle_request('POST')

    def do_PUT(self):
        self._handle_request('PUT')

    def do_DELETE(self):
        self._handle_request('DELETE')

    def do_HEAD(self):
        self._handle_request('HEAD')

    def do_OPTIONS(self):
        self._handle_request('OPTIONS')

    def do_PATCH(self):
        self._handle_request('PATCH')