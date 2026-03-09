#!/usr/bin/env python3
"""
HTTP Forwarding Server - HTTP 转发服务器（增强日志版）

使用方式：
  http://127.0.0.1:12345/http://httpbin.org/ip
  http://127.0.0.1:12345/https://httpbin.org/ip

功能特性：
- 完整的请求/响应日志记录
- 从 URL 路径解析目标地址并转发请求
- 支持流式传输（chunked encoding）
- 并发处理多个请求
- 彩色终端输出
"""

import argparse
import http.server
import http.client
import socketserver
import ssl
import socket
import time
import sys
import os
import re
import json
from urllib.parse import urlparse
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
from io import BytesIO

# 颜色定义
class Colors:
    """终端颜色代码"""
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

    @classmethod
    def disable(cls):
        """禁用颜色输出"""
        for attr in ['RESET', 'RED', 'GREEN', 'YELLOW', 'BLUE', 
                     'MAGENTA', 'CYAN', 'WHITE', 'BOLD', 'DIM']:
            setattr(cls, attr, '')


def format_size(size: int) -> str:
    """格式化文件大小"""
    if size == 0:
        return "0B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if abs(size) < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}TB"


def format_duration(seconds: float) -> str:
    """格式化耗时"""
    if seconds < 0.001:
        return f"{seconds*1000000:.0f}μs"
    elif seconds < 1:
        return f"{seconds*1000:.1f}ms"
    else:
        return f"{seconds:.2f}s"


def is_text_content(content_type: str) -> bool:
    """判断是否为文本类型内容"""
    if not content_type:
        return False
    text_types = [
        'text/', 'application/json', 'application/xml', 'application/javascript',
        'application/x-www-form-urlencoded', 'application/x-www-form-urlencoded',
    ]
    for t in text_types:
        if t in content_type.lower():
            return True
    return False


def format_body(body: bytes, content_type: str = None) -> str:
    """格式化 body 内容（完整保留，不截断）"""
    if not body:
        return "(empty)"
    
    size = len(body)
    
    # 判断是否为文本类型
    if content_type and not is_text_content(content_type):
        return f"({format_size(size)} binary data)"
    
    # 尝试解码为文本（完整保留）
    try:
        text = body.decode('utf-8')
        
        # 尝试格式化 JSON
        if content_type and 'json' in content_type.lower():
            try:
                obj = json.loads(text)
                text = json.dumps(obj, indent=2, ensure_ascii=False)
            except:
                pass
        
        return text
    except UnicodeDecodeError:
        return f"({format_size(size)} binary data)"


class RequestLogger:
    """请求日志记录器"""
    
    def __init__(self, log_file: str):
        self.log_file = log_file
        self.lock = None  # 简化，不使用锁
        
    def log_request_response(
        self,
        method: str,
        url: str,
        request_headers: Dict[str, str],
        request_body: bytes,
        response_status: int,
        response_reason: str,
        response_headers: list,
        response_body: bytes,
        duration: float
    ):
        """记录完整的请求和响应"""
        
        separator = "═" * 60
        sub_separator = "─" * 60
        
        lines = []
        
        # ===== 请求部分 =====
        lines.append(separator)
        lines.append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] REQUEST")
        lines.append(sub_separator)
        lines.append(f"{method} {url}")
        lines.append(sub_separator)
        
        # 请求头
        if request_headers:
            lines.append("Headers:")
            max_key_len = max(len(k) for k in request_headers.keys())
            for key, value in request_headers.items():
                lines.append(f"  {key:<{max_key_len}}: {value}")
        else:
            lines.append("Headers: (none)")
        
        # 请求体
        lines.append("")
        content_type = request_headers.get('Content-Type', '')
        lines.append("Body:")
        lines.append("  " + format_body(request_body, content_type).replace("\n", "\n  "))
        
        # ===== 响应部分 =====
        lines.append(separator)
        lines.append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RESPONSE")
        lines.append(sub_separator)
        lines.append(f"Status: {response_status} {response_reason}")
        lines.append(sub_separator)
        
        # 响应头
        if response_headers:
            lines.append("Headers:")
            headers_dict = {k: v for k, v in response_headers}
            max_key_len = max(len(k) for k, _ in response_headers)
            for key, value in response_headers:
                lines.append(f"  {key:<{max_key_len}}: {value}")
        else:
            lines.append("Headers: (none)")
        
        # 响应体
        lines.append("")
        resp_content_type = dict(response_headers).get('Content-Type', '')
        lines.append("Body:")
        lines.append("  " + format_body(response_body, resp_content_type).replace("\n", "\n  "))
        
        lines.append(separator)
        lines.append(f"Duration: {format_duration(duration)}")
        lines.append(separator)
        lines.append("")  # 空行分隔不同请求
        
        # 写入文件
        log_content = "\n".join(lines)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_content)
        
        return log_content


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
                        # 设置 SSL 超时
                        context.check_hostname = False
                        context.verify_mode = ssl.CERT_NONE  # 允许自签名证书
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
                    
                    # 添加 Connection: close 确保连接正确关闭
                    forward_headers['Connection'] = 'close'
                    
                    # 发送请求到目标服务器
                    conn.request(method, target_path, body=request_body, headers=forward_headers)
                    
                    # 获取响应
                    response = conn.getresponse()
                    break  # 成功则跳出重试循环
                    
                except (http.client.HTTPException, socket.timeout, socket.error, ConnectionError, OSError) as e:
                    last_error = e
                    retry_count += 1
                    if conn:
                        try:
                            conn.close()
                        except:
                            pass
                    if retry_count < max_retries:
                        time.sleep(0.5 * retry_count)  # 递增延迟
                    continue
            
            if retry_count >= max_retries:
                raise last_error or Exception("Connection failed after retries")
            
            # ===== 收集响应信息 =====
            response_status = response.status
            response_reason = response.reason
            response_headers = response.getheaders()
            
            # 读取响应体（需要缓存以便记录日志）
            response_body = response.read()
            
            # ===== 发送响应给客户端 =====
            self.send_response(response_status, response_reason)

            for key, value in response_headers:
                if key.lower() not in ('transfer-encoding', 'connection'):
                    self.send_header(key, value)

            # 确保设置正确的 Content-Length
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
                    duration=duration
                )
            
            # 终端简短输出
            self._log_terminal(method, full_url, response_status, len(response_body), duration)
            
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
            # 确保连接被关闭
            if conn:
                try:
                    conn.close()
                except:
                    pass

    def _log_terminal(self, method: str, url: str, status: int, size: int, duration: float):
        """终端简短输出"""
        # 状态码颜色
        if status < 300:
            status_color = Colors.GREEN
        elif status < 400:
            status_color = Colors.YELLOW
        else:
            status_color = Colors.RED
        
        log_msg = (
            f"{Colors.CYAN}{method}{Colors.RESET} "
            f"{url} "
            f"{status_color}{status}{Colors.RESET} "
            f"{Colors.MAGENTA}{format_size(size)}{Colors.RESET} "
            f"{Colors.BLUE}{format_duration(duration)}{Colors.RESET}"
        )
        print(f"{Colors.DIM}{datetime.now().strftime('%H:%M:%S')}{Colors.RESET} {log_msg}")

    def _log_error(self, method: str, url: str, error: str):
        """记录错误日志"""
        print(f"{Colors.DIM}{datetime.now().strftime('%H:%M:%S')}{Colors.RESET} "
              f"{Colors.RED}[ERROR]{Colors.RESET} {method} {url} - {error}")
        
        if hasattr(self.server, 'log_file') and self.server.log_file:
            with open(self.server.log_file, 'a', encoding='utf-8') as f:
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


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """支持多线程的 TCP 服务器"""
    allow_reuse_address = True
    daemon_threads = True
    log_file = None
    logger = None


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='HTTP Forwarding Server - HTTP 转发服务器（增强日志版）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用方式:
  在 URL 前添加代理服务器地址:
    http://127.0.0.1:12345/http://httpbin.org/ip
    http://127.0.0.1:12345/https://httpbin.org/ip

示例:
  %(prog)s                    # 使用默认端口 12345
  %(prog)s -p 8080            # 使用端口 8080
  %(prog)s -p 8080 --no-color # 禁用颜色输出
        """
    )
    parser.add_argument(
        '-p', '--port',
        type=int,
        default=12345,
        help='服务器端口 (默认: 12345)'
    )
    parser.add_argument(
        '--no-color',
        action='store_true',
        help='禁用终端颜色输出'
    )
    parser.add_argument(
        '--log-file',
        default='logs/proxy.log',
        help='日志文件路径 (默认: logs/proxy.log)'
    )
    
    args = parser.parse_args()
    
    # 禁用颜色
    if args.no_color:
        Colors.disable()
    
    # 确保日志目录存在
    log_dir = os.path.dirname(args.log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    
    # 创建日志记录器
    logger = RequestLogger(args.log_file)
    
    # 启动服务器
    try:
        server = ThreadedTCPServer(('0.0.0.0', args.port), ForwardingHandler)
        server.log_file = args.log_file
        server.logger = logger
        
        print(f"\n{Colors.BOLD}{Colors.CYAN}HTTP Forwarding Server{Colors.RESET}")
        print(f"{Colors.GREEN}✓{Colors.RESET} 服务器已启动")
        print(f"{Colors.BLUE}→{Colors.RESET} 监听端口: {Colors.YELLOW}{args.port}{Colors.RESET}")
        print(f"{Colors.BLUE}→{Colors.RESET} 日志文件: {Colors.YELLOW}{args.log_file}{Colors.RESET}")
        print(f"\n{Colors.BOLD}使用方式:{Colors.RESET}")
        print(f"  {Colors.DIM}http://127.0.0.1:{args.port}/http://example.com{Colors.RESET}")
        print(f"  {Colors.DIM}http://127.0.0.1:{args.port}/https://example.com{Colors.RESET}")
        print(f"\n{Colors.DIM}按 Ctrl+C 停止服务器{Colors.RESET}\n")
        
        # 记录启动日志
        with open(args.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] SERVER STARTED on port {args.port}\n")
            f.write(f"{'='*60}\n")
        
        server.serve_forever()
        
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}正在关闭服务器...{Colors.RESET}")
        with open(args.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] SERVER STOPPED\n")
            f.write(f"{'='*60}\n\n")
        server.shutdown()
        server.server_close()
    except OSError as e:
        if e.errno == 98:
            print(f"{Colors.RED}错误: 端口 {args.port} 已被占用{Colors.RESET}")
        else:
            print(f"{Colors.RED}错误: {e}{Colors.RESET}")
        sys.exit(1)


if __name__ == '__main__':
    main()