"""日志记录模块"""

import threading
from datetime import datetime
from typing import Dict

from utils.format import format_body, format_duration


class RequestLogger:
    """请求日志记录器"""

    def __init__(self, log_file: str, db=None, enable_file_log: bool = False):
        self.log_file = log_file
        self.db = db
        self.enable_file_log = enable_file_log
        self.lock = threading.Lock()

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
        duration: float,
        is_streaming: bool = False
    ):
        """记录完整的请求和响应"""

        # 保存到数据库
        request_id = None
        if self.db:
            request_id = self.db.save_request(
                method=method,
                url=url,
                request_headers=request_headers,
                request_body=request_body,
                response_status=response_status,
                response_reason=response_reason,
                response_headers=response_headers,
                response_body=response_body,
                duration=duration,
                is_streaming=is_streaming
            )

        # 同时保存到日志文件
        separator = "═" * 60
        sub_separator = "─" * 60

        lines = []

        # ===== 请求部分 =====
        lines.append(separator)
        lines.append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] REQUEST [{request_id or 'N/A'}]")
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
        streaming_note = " (streaming)" if is_streaming else ""
        lines.append(f"Status: {response_status} {response_reason}{streaming_note}")
        lines.append(sub_separator)

        # 响应头
        if response_headers:
            lines.append("Headers:")
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

        # 写入文件（如果启用）
        if self.enable_file_log:
            log_content = "\n".join(lines)
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_content)

        return request_id