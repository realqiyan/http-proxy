"""HTTP 代理处理器"""

import http.server
import http.client
import ssl
import socket
import re
import time
import traceback
from io import BytesIO
from urllib.parse import urlparse
from datetime import datetime
from typing import Optional, Tuple, Dict

from utils.colors import Colors
from utils.format import format_size, format_duration


class ForwardingHandler(http.server.BaseHTTPRequestHandler):
    """HTTP 转发请求处理器"""

    protocol_version = 'HTTP/1.1'
    timeout = 60  # 默认连接超时时间（可被 server.connect_timeout 覆盖）

    def setup(self):
        """初始化连接"""
        # 使用服务器配置的超时时间，如果没有配置则使用默认值
        timeout_val = getattr(self.server, 'connect_timeout', self.timeout)
        self.request.settimeout(timeout_val)
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
        """检测是否为流式响应

        注意：text/event-stream 的检测独立于 Transfer-Encoding 检查，
        因为 SSE 规范要求服务器必须使用流式传输，检测 Content-Type 即可。

        隐式流式检测：当响应使用 chunked 编码且没有 Content-Length 时，
        排除常见的非流式 Content-Type 后，视为流式响应。
        """
        content_type = headers.get('Content-Type', '').lower()
        transfer_encoding = headers.get('Transfer-Encoding', '').lower()
        content_length = headers.get('Content-Length')

        # SSE (Server-Sent Events) - 仅检测 Content-Type，无需 Transfer-Encoding
        if 'text/event-stream' in content_type:
            return True

        # Chunked encoding 且可能是流式
        if 'chunked' in transfer_encoding:
            # 已知的流式 Content-Type
            streaming_types = ['text/event-stream', 'application/x-ndjson', 'application/stream+json']
            if any(t in content_type for t in streaming_types):
                return True

            # 隐式流式检测：chunked + 无 Content-Length + 非常见静态内容类型
            # 排除常见的非流式类型以减少误判
            if content_length is None:
                non_streaming_types = [
                    'text/html', 'application/json', 'application/javascript',
                    'text/css', 'image/', 'application/pdf', 'application/xml'
                ]
                if not any(t in content_type for t in non_streaming_types):
                    return True

        return False

    def _handle_streaming_response(self, response, status: int, reason: str, headers: list) -> bytes:
        """处理流式响应，边读边转发，同时缓存部分内容用于日志

        流式响应期间使用扩展的超时时间（stream_timeout），避免长对话生成中断。
        """
        # 获取流式超时配置
        stream_timeout = getattr(self.server, 'stream_timeout', 300)

        # 发送响应头
        self.send_response(status, reason)

        for key, value in headers:
            if key.lower() not in ('connection',):
                self.send_header(key, value)

        self.end_headers()

        # 设置客户端 socket 为阻塞模式，避免超时中断
        original_timeout = self.request.gettimeout()
        self.request.settimeout(None)

        # 设置上游 socket 超时
        # HTTPResponse.read() 没有超时参数，需要访问底层 socket
        try:
            if hasattr(response, 'fp') and hasattr(response.fp, '_fp'):
                response.fp._fp.settimeout(stream_timeout)
        except (AttributeError, socket.error):
            pass  # 无法访问底层 socket，使用默认行为

        # 缓存前 64KB 用于日志
        cached_body = BytesIO()
        cache_limit = 65536
        total_size = 0

        try:
            # SSE 事件边界处理：读取数据块，按 \n\n 边界切分后立即发送
            # 注意：必须用 response.read() 而非 response.fp.readline()，
            # 因为后者会读取原始 chunked 流（包含 chunk size 标记如 "7c\r\n"）
            buffer = b''
            client_disconnected = False

            while not client_disconnected:
                # 读取较大的块以提高效率，然后按事件边界切分
                chunk = response.read(4096)
                if not chunk:
                    # 上游关闭连接，发送剩余缓冲区内容
                    if buffer:
                        self.wfile.write(buffer)
                        self.wfile.flush()
                        if cached_body.tell() < cache_limit:
                            remaining = cache_limit - cached_body.tell()
                            cached_body.write(buffer[:remaining])
                        total_size += len(buffer)
                    break

                buffer += chunk

                # 按 \n\n 边界切分，立即发送完整事件
                while b'\n\n' in buffer and not client_disconnected:
                    # 找到事件边界
                    idx = buffer.find(b'\n\n') + 2  # 包含 \n\n
                    event = buffer[:idx]
                    buffer = buffer[idx:]

                    # 发送完整事件
                    try:
                        self.wfile.write(event)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        # 客户端断开连接
                        client_disconnected = True
                        break

                    # 缓存用于日志
                    if cached_body.tell() < cache_limit:
                        remaining = cache_limit - cached_body.tell()
                        cached_body.write(event[:remaining])

                    total_size += len(event)

        except socket.timeout:
            # 流式传输期间的超时 - 记录但不中断（可能上游暂停）
            print(f"{Colors.YELLOW}[STREAMING] Socket timeout after {stream_timeout}s{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.YELLOW}[STREAMING] Error: {e}{Colors.RESET}")

        finally:
            # 恢复原始超时设置
            if original_timeout is not None:
                try:
                    self.request.settimeout(original_timeout)
                except:
                    pass

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
            connect_timeout = getattr(self.server, 'connect_timeout', 60)

            while retry_count < max_retries:
                try:
                    if scheme == 'https':
                        context = ssl.create_default_context()
                        context.check_hostname = False
                        context.verify_mode = ssl.CERT_NONE
                        conn = http.client.HTTPSConnection(host, port, context=context, timeout=connect_timeout)
                    else:
                        conn = http.client.HTTPConnection(host, port, timeout=connect_timeout)

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
            if not getattr(self, 'headers_sent', False):
                try:
                    self.send_error(502, f'Bad Gateway: {e}')
                except:
                    pass
        except socket.timeout as e:
            self._log_error(method, full_url, f'Connection timeout: {e}')
            if not getattr(self, 'headers_sent', False):
                try:
                    self.send_error(504, f'Gateway Timeout: {e}')
                except:
                    pass
        except (socket.error, ConnectionError, OSError) as e:
            self._log_error(method, full_url, f'Connection error: {e}')
            if not getattr(self, 'headers_sent', False):
                try:
                    self.send_error(502, f'Bad Gateway: Connection failed - {e}')
                except:
                    pass
        except Exception as e:
            self._log_error(method, full_url, f'{e}\n{traceback.format_exc()}')
            if not getattr(self, 'headers_sent', False):
                try:
                    self.send_error(500, f'Internal Error: {e}')
                except:
                    pass
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