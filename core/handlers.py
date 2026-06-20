"""HTTP 代理处理器"""

import http.server
import socket
import re
import time
import traceback
import ipaddress
from io import BytesIO
from urllib.parse import urlparse
from datetime import datetime
from typing import Optional, Tuple, Dict

# requests 延迟到 _handle_request 内导入，使本模块在缺少依赖时仍可被
# proxy_server 加载（从而让 proxy_server 给出友好的安装提示，且 stop/status
# 等子命令不依赖 requests）。
from utils.colors import Colors
from utils.format import format_size, format_duration


# 阻止访问内部地址，防止 SSRF 攻击
BLOCKED_HOSTS = ['localhost', '169.254.169.254']
BLOCKED_SUFFIXES = ['.internal', '.local', '.localhost']

# 请求/响应体大小限制
MAX_REQUEST_BODY_SIZE = 100 * 1024 * 1024   # 100MB
MAX_RESPONSE_BODY_SIZE = 200 * 1024 * 1024  # 200MB


def _is_private_ip(host: str) -> bool:
    """检查主机名是否解析为内部/私有 IP 地址（防止 SSRF）"""
    try:
        addrs = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in addrs:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return True
    except (socket.gaierror, ValueError):
        pass
    return False


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
        # URL fragment 不转发给上游（HTTP 规范：fragment 是客户端行为）

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

    def _handle_streaming_response(self, response, status: int, reason: str, headers) -> bytes:
        """处理流式响应，边读边转发，同时缓存部分内容用于日志

        流式响应期间使用扩展的超时时间（stream_timeout），避免长对话生成中断。

        通过 requests 的 response.raw.read(decode_content=False) 读取已去 chunked 帧
        的原始字节（保留 Content-Encoding 如 gzip 的压缩字节，保证字节保真），再用
        _encode_chunk 重新编码为 chunked 帧发给客户端，确保客户端收到合法的 chunked 流。
        上游若未用 chunked 且无 Content-Length，则对客户端注入 chunked 编码。
        """
        # 获取流式超时配置
        stream_timeout = getattr(self.server, 'stream_timeout', 300)

        # 确定响应头信息（headers 为 CaseInsensitiveDict，get 大小写不敏感）
        content_type = headers.get('Content-Type', '').lower()
        transfer_encoding = headers.get('Transfer-Encoding', '').lower()
        content_length = headers.get('Content-Length')
        # 上游 chunked 或无 Content-Length 时，对客户端统一使用 chunked 编码
        use_chunked = 'chunked' in transfer_encoding or content_length is None

        # 发送响应头
        self.send_response(status, reason)
        for key, value in headers.items():
            kl = key.lower()
            if kl == 'connection':
                continue
            if use_chunked and kl == 'content-length':
                # 改用 chunked 编码，去掉上游的 Content-Length
                continue
            self.send_header(key, value)
        if use_chunked and 'chunked' not in transfer_encoding:
            # 上游非 chunked 但无 Content-Length：注入 chunked
            self.send_header('Transfer-Encoding', 'chunked')
        self.end_headers()
        self.headers_sent = True  # 标记已发送响应头

        # 设置客户端 socket 超时（使用流式超时，防止慢客户端永久阻塞线程）
        original_timeout = self.request.gettimeout()
        self.request.settimeout(stream_timeout)

        # 缓存前 64KB 用于日志
        cached_body = BytesIO()
        cache_limit = 65536
        total_size = 0
        stream_failed = False
        client_disconnected = False
        raw = response.raw

        try:
            while not client_disconnected:
                try:
                    # decode_content=False：保留 Content-Encoding 原始字节（字节保真）
                    chunk = raw.read(8192, decode_content=False)
                except socket.timeout:
                    stream_failed = True
                    print(f"{Colors.YELLOW}[STREAMING] Socket timeout after {stream_timeout}s{Colors.RESET}")
                    break
                except Exception as e:
                    stream_failed = True
                    print(f"{Colors.YELLOW}[STREAMING] Upstream error: {e}{Colors.RESET}")
                    break

                if not chunk:
                    # 上游关闭连接，流结束
                    break

                out = self._encode_chunk(chunk) if use_chunked else chunk
                try:
                    self.wfile.write(out)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    # 客户端主动断开，正常情况，不记错误
                    client_disconnected = True
                    break

                if cached_body.tell() < cache_limit:
                    remaining = cache_limit - cached_body.tell()
                    cached_body.write(chunk[:remaining])
                total_size += len(chunk)

            # chunked 结束标记
            if use_chunked and not client_disconnected:
                try:
                    self.wfile.write(b'0\r\n\r\n')
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    client_disconnected = True

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
                except Exception:
                    pass
            # 关闭上游响应，释放连接资源
            try:
                response.close()
            except Exception:
                pass

        # 返回缓存的响应体（可能被截断）
        result = cached_body.getvalue()
        cached_body.close()
        if total_size > cache_limit or stream_failed:
            status_text = 'FAILED' if stream_failed else 'complete'
            result += f"\n\n... (truncated, total {format_size(total_size)}, {status_text})".encode('utf-8')

        return result

    def _encode_chunk(self, data: bytes) -> bytes:
        """将数据编码为 HTTP chunked 格式"""
        size = len(data)
        return f'{size:x}\r\n'.encode('utf-8') + data + b'\r\n'

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
        if _is_private_ip(host):
            self.send_error(403, 'Forbidden: Internal addresses not allowed')
            return
        full_url = f"{scheme}://{host}:{port}{target_path}"

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
            if content_length > MAX_REQUEST_BODY_SIZE:
                self.send_error(413, f'Request Entity Too Large: max {MAX_REQUEST_BODY_SIZE // (1024*1024)}MB')
                return
            request_body = self.rfile.read(content_length) if content_length > 0 else b''

            # 准备转发的请求头（排除 hop-by-hop 头与 host，由 requests 按目标 URL 设置）
            forward_headers = {}
            for key, value in self.headers.items():
                if key.lower() not in ('connection', 'keep-alive', 'proxy-authenticate',
                                       'proxy-authorization', 'te', 'trailers',
                                       'transfer-encoding', 'upgrade', 'host'):
                    forward_headers[key] = value

            connect_timeout = getattr(self.server, 'connect_timeout', 60)
            stream_timeout = getattr(self.server, 'stream_timeout', 300)
            verify_ssl = getattr(self.server, 'verify_ssl', False)

            # 延迟导入 requests（见模块顶部说明）
            import requests
            from requests.adapters import HTTPAdapter

            # 幂等方法：连接错误可重试；非幂等（POST/PATCH）仅在连接阶段超时重试，
            # 避免对已发出的请求重试导致重复计费。
            idempotent = method.upper() in ('GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE')

            # 连接目标服务器并发送请求（带重试）
            # timeout=(connect, read)：连接阶段用 connect_timeout，读取阶段（等待响应头/读体）
            # 用 stream_timeout，使长耗时 LLM 响应不再被 60s 杀掉。
            max_retries = 3
            retry_count = 0
            last_error = None
            response = None

            while retry_count < max_retries:
                # 每请求新建 Session（与原 Connection: close 语义一致、线程安全），
                # 禁用 urllib3 自动重试，由本循环显式控制。
                session = requests.Session()
                session.mount('https://', HTTPAdapter(max_retries=0))
                session.mount('http://', HTTPAdapter(max_retries=0))
                got_response = False
                try:
                    response = session.request(
                        method, full_url,
                        data=request_body,
                        headers=forward_headers,
                        stream=True,
                        allow_redirects=False,
                        verify=verify_ssl,
                        timeout=(connect_timeout, stream_timeout),
                    )
                    got_response = True
                    break  # 成功拿到响应头

                except requests.exceptions.ConnectTimeout as e:
                    # 连接阶段超时：请求未发出，安全重试
                    last_error = e
                    retry_count += 1
                except requests.exceptions.ReadTimeout as e:
                    # 读取阶段超时：请求已发出（可能已被上游处理），不重试，避免重复计费
                    self._log_error(method, full_url, f'Connection timeout: {e}')
                    if not getattr(self, 'headers_sent', False):
                        try:
                            self.send_error(504, f'Gateway Timeout: {e}')
                        except Exception:
                            pass
                    return
                except requests.exceptions.ConnectionError as e:
                    # 连接错误：仅幂等方法重试；POST/PATCH 不重试
                    last_error = e
                    if idempotent:
                        retry_count += 1
                    else:
                        self._log_error(method, full_url, f'Connection error: {e}')
                        if not getattr(self, 'headers_sent', False):
                            try:
                                self.send_error(502, f'Bad Gateway: Connection failed - {e}')
                            except Exception:
                                pass
                        return
                except requests.exceptions.RequestException as e:
                    last_error = e
                    retry_count += 1
                finally:
                    # 失败时关闭 session；成功时 response 持有连接，稍后关闭
                    if not got_response:
                        session.close()

                if retry_count < max_retries:
                    time.sleep(0.5 * retry_count)

            if response is None:
                # 重试耗尽
                e = last_error or Exception("Connection failed after retries")
                self._log_error(method, full_url, f'Connection error: {e}')
                if not getattr(self, 'headers_sent', False):
                    try:
                        self.send_error(502, f'Bad Gateway: Connection failed - {e}')
                    except Exception:
                        pass
                return

            # ===== 收集响应信息并转发 =====
            try:
                response_status = response.status_code
                response_reason = response.reason or ''
                response_headers = list(response.headers.items())
                headers_dict = response.headers  # CaseInsensitiveDict

                # 检测是否为流式响应
                is_streaming = self._is_streaming_response(headers_dict)

                if is_streaming:
                    # 流式响应处理
                    response_body = self._handle_streaming_response(
                        response, response_status, response_reason, headers_dict)
                else:
                    # 普通响应：读取完整响应体
                    # decode_content=False 保留 Content-Encoding 原始字节（gzip 等），与原行为一致
                    response_body = b''
                    too_large = False
                    while True:
                        chunk = response.raw.read(65536, decode_content=False)
                        if not chunk:
                            break
                        response_body += chunk
                        if len(response_body) > MAX_RESPONSE_BODY_SIZE:
                            too_large = True
                            break

                    if too_large:
                        self.send_error(502, f'Bad Gateway: Response exceeded {MAX_RESPONSE_BODY_SIZE // (1024*1024)}MB limit')
                        return

                    # ===== 发送响应给客户端 =====
                    self.send_response(response_status, response_reason)
                    for key, value in response_headers:
                        if key.lower() not in ('transfer-encoding', 'connection'):
                            self.send_header(key, value)
                    self.send_header('Content-Length', str(len(response_body)))
                    self.end_headers()
                    self.headers_sent = True  # 标记已发送响应头

                    try:
                        self.wfile.write(response_body)
                    except (BrokenPipeError, ConnectionResetError):
                        # 客户端主动断开，正常情况，不记错误
                        pass

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

            finally:
                try:
                    response.close()
                except Exception:
                    pass

        except Exception as e:
            self._log_error(method, full_url, f'{e}\n{traceback.format_exc()}')
            if not getattr(self, 'headers_sent', False):
                try:
                    self.send_error(500, f'Internal Error: {e}')
                except Exception:
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