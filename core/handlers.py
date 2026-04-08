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


# 阻止访问内部地址，防止 SSRF 攻击
BLOCKED_HOSTS = ['localhost', '127.0.0.1', '169.254.169.254', '::1', '0.0.0.0']
BLOCKED_SUFFIXES = ['.internal', '.local', '.localhost']


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

    def handle(self):
        """处理连接，捕获早期断开的错误"""
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, socket.error):
            # 客户端在请求完成前断开连接 - 正常情况，静默处理
            pass
        except Exception as e:
            # 其他异常记录警告，便于调试
            print(f"{Colors.DIM}{datetime.now().strftime('%H:%M:%S')}{Colors.RESET} "
                  f"{Colors.YELLOW}[WARN]{Colors.RESET} Unexpected error in handle(): {type(e).__name__}: {e}")

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

        关键：对于 chunked 流式响应，直接透传原始数据（不经过 HTTPResponse 解码），
        否则客户端收到的是解码后的数据但头中保留了 Transfer-Encoding: chunked，导致解析错误。
        """
        # 获取流式超时配置
        stream_timeout = getattr(self.server, 'stream_timeout', 300)

        # 确定响应头信息
        headers_dict = dict(headers)
        content_type = headers_dict.get('Content-Type', '').lower()
        transfer_encoding = headers_dict.get('Transfer-Encoding', '').lower()
        use_chunked = 'chunked' in transfer_encoding

        # 发送响应头（对于 chunked 流式，保留 Transfer-Encoding）
        self.send_response(status, reason)

        for key, value in headers:
            if key.lower() not in ('connection',):
                self.send_header(key, value)

        self.end_headers()
        self.headers_sent = True  # 标记已发送响应头

        # 设置客户端 socket 为阻塞模式，避免超时中断
        original_timeout = self.request.gettimeout()
        self.request.settimeout(None)

        # 设置上游 socket 超时
        try:
            if hasattr(response, 'fp') and hasattr(response.fp, '_fp'):
                response.fp._fp.settimeout(stream_timeout)
        except (AttributeError, socket.error):
            pass  # 无法访问底层 socket，使用默认行为

        # 缓存前 64KB 用于日志
        cached_body = BytesIO()
        cache_limit = 65536
        total_size = 0
        stream_failed = False

        try:
            client_disconnected = False

            # 对于 chunked 编码的响应，直接透传原始数据流
            # 因为 HTTPResponse.read() 会自动解码 chunked，去掉 size 标记
            # 但客户端期望收到完整的 chunked 格式数据（包括 size 标记和结束标记 0\r\n\r\n）
            if use_chunked:
                # 直接读取原始 socket 数据（透传 chunked 格式）
                raw_socket = None
                try:
                    if hasattr(response, 'fp') and hasattr(response.fp, '_fp'):
                        raw_socket = response.fp._fp
                except (AttributeError, socket.error):
                    pass

                if raw_socket:
                    # 透传模式：直接从原始 socket 读取并转发
                    while not client_disconnected:
                        try:
                            chunk = raw_socket.recv(8192)
                        except socket.timeout:
                            stream_failed = True
                            print(f"{Colors.YELLOW}[STREAMING] Socket timeout after {stream_timeout}s{Colors.RESET}")
                            break
                        except socket.error as e:
                            if e.errno == 11:  # EAGAIN/EWOULDBLOCK - 临时无数据
                                continue
                            stream_failed = True
                            print(f"{Colors.YELLOW}[STREAMING] Socket error: {e}{Colors.RESET}")
                            break

                        if not chunk:
                            # 上游关闭连接，chunked 流结束
                            break

                        # 直接转发原始 chunked 数据
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            client_disconnected = True
                            stream_failed = True
                            break

                        # 缓存用于日志（解码后存储，便于查看）
                        if cached_body.tell() < cache_limit:
                            # 尝试解码部分数据用于日志显示
                            try:
                                # 去掉 chunk 标记，只保留实际内容
                                decoded_chunk = self._decode_chunked_sample(chunk, cached_body.tell())
                                remaining = cache_limit - cached_body.tell()
                                cached_body.write(decoded_chunk[:remaining])
                            except:
                                # 解码失败，直接存储原始数据
                                remaining = cache_limit - cached_body.tell()
                                cached_body.write(chunk[:remaining])

                        total_size += len(chunk)
                else:
                    # 无法访问原始 socket，回退到普通读取
                    # 但需要重新编码为 chunked 格式发送给客户端
                    buffer = b''
                    while not client_disconnected:
                        chunk = response.read(4096)
                        if not chunk:
                            # 发送剩余数据和 chunked 结束标记
                            if buffer:
                                chunk_data = self._encode_chunk(buffer)
                                self.wfile.write(chunk_data)
                                self.wfile.flush()
                                total_size += len(chunk_data)
                                if cached_body.tell() < cache_limit:
                                    remaining = cache_limit - cached_body.tell()
                                    cached_body.write(buffer[:remaining])
                            # 发送结束标记
                            self.wfile.write(b'0\r\n\r\n')
                            self.wfile.flush()
                            break

                        buffer += chunk

                        # 按事件边界切分，用 chunked 格式发送
                        delimiter = b'\n\n' if 'text/event-stream' in content_type else b'\n'
                        while delimiter in buffer and not client_disconnected:
                            idx = buffer.find(delimiter) + len(delimiter)
                            event = buffer[:idx]
                            buffer = buffer[idx:]

                            # 编码为 chunk 格式发送
                            chunk_data = self._encode_chunk(event)
                            try:
                                self.wfile.write(chunk_data)
                                self.wfile.flush()
                            except (BrokenPipeError, ConnectionResetError):
                                client_disconnected = True
                                stream_failed = True
                                break

                            total_size += len(chunk_data)
                            if cached_body.tell() < cache_limit:
                                remaining = cache_limit - cached_body.tell()
                                cached_body.write(event[:remaining])

                    # 发送 chunked 结束标记
                    if not client_disconnected:
                        self.wfile.write(b'0\r\n\r\n')
                        self.wfile.flush()
            else:
                # 非 chunked 流式响应（如 NDJSON），直接转发数据
                # SSE 使用 \n\n，NDJSON 使用 \n
                delimiter = b'\n\n' if 'text/event-stream' in content_type else b'\n'
                buffer = b''

                while not client_disconnected:
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

                    # 按事件边界切分，立即发送完整事件
                    while delimiter in buffer and not client_disconnected:
                        idx = buffer.find(delimiter) + len(delimiter)
                        event = buffer[:idx]
                        buffer = buffer[idx:]

                        try:
                            self.wfile.write(event)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            client_disconnected = True
                            stream_failed = True
                            break

                        if cached_body.tell() < cache_limit:
                            remaining = cache_limit - cached_body.tell()
                            cached_body.write(event[:remaining])

                        total_size += len(event)

        except socket.timeout:
            stream_failed = True
            print(f"{Colors.YELLOW}[STREAMING] Socket timeout after {stream_timeout}s{Colors.RESET}")
        except Exception as e:
            stream_failed = True
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
        if total_size > cache_limit or stream_failed:
            status_text = 'FAILED' if stream_failed else 'complete'
            result += f"\n\n... (truncated, total {format_size(total_size)}, {status_text})".encode('utf-8')

        return result

    def _encode_chunk(self, data: bytes) -> bytes:
        """将数据编码为 HTTP chunked 格式"""
        size = len(data)
        return f'{size:x}\r\n'.encode('utf-8') + data + b'\r\n'

    def _decode_chunked_sample(self, raw_data: bytes, offset: int) -> bytes:
        """从原始 chunked 数据中解码一小段用于日志显示（简化版）"""
        # 简化处理：尝试去除 chunk size 标记
        # 格式: size\r\n data\r\n
        try:
            result = b''
            pos = 0
            while pos < len(raw_data) and len(result) < 4096:
                # 找到 chunk size
                end_size = raw_data.find(b'\r\n', pos)
                if end_size == -1:
                    result += raw_data[pos:]
                    break

                size_hex = raw_data[pos:end_size].decode('utf-8')
                size = int(size_hex, 16)
                data_start = end_size + 2
                data_end = data_start + size

                if data_end > len(raw_data):
                    result += raw_data[data_start:]
                    break

                result += raw_data[data_start:data_end]
                pos = data_end + 2  # 跳过 chunk 后的 \r\n

            return result
        except:
            return raw_data

    def _handle_request(self, method: str):
        """处理请求并转发"""
        start_time = time.time()

        # 解析目标 URL
        target = self._parse_target_url()
        if not target:
            self.send_error(400, 'Bad Request: Invalid URL format. Use /http://example.com/path')
            return

        scheme, host, port, target_path = target

        # SSRF 防护：检查是否为内部地址
        host_lower = host.lower()
        if host_lower in BLOCKED_HOSTS:
            self.send_error(403, 'Forbidden: Internal addresses not allowed')
            return
        if any(host_lower.endswith(suffix) for suffix in BLOCKED_SUFFIXES):
            self.send_error(403, 'Forbidden: Internal addresses not allowed')
            return
        full_url = f"{scheme}://{host}:{port}{target_path}"

        conn = None
        try:
            # ===== 收集请求信息 =====
            request_headers = {}
            for key, value in self.headers.items():
                request_headers[key] = value

            # 读取请求体（验证 Content-Length）
            content_length_str = self.headers.get('Content-Length', '0')
            try:
                content_length = int(content_length_str)
            except ValueError:
                self.send_error(400, 'Bad Request: Invalid Content-Length')
                return
            if content_length < 0:
                self.send_error(400, 'Bad Request: Negative Content-Length')
                return
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
                        verify_ssl = getattr(self.server, 'verify_ssl', False)
                        if verify_ssl:
                            context.check_hostname = True
                            context.verify_mode = ssl.CERT_REQUIRED
                        else:
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
                self.headers_sent = True  # 标记已发送响应头

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