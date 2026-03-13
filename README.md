# HTTP Proxy Logger

一个专注于请求日志记录的 HTTP 代理服务器。通过简单的 URL 前缀转发请求，自动记录完整的请求/响应数据，提供 Web 界面查看和分析。

## 核心功能：日志记录

### 多维度日志存储

| 存储方式 | 说明 | 默认状态 |
|---------|------|---------|
| **SQLite 数据库** | 持久化存储，支持查询、筛选、统计 | 默认启用 |
| **Web Dashboard** | 可视化查看请求详情，敏感信息自动脱敏 | 默认启用 |
| **日志文件** | 完整的请求/响应文本日志 | 默认关闭 |
| **终端输出** | 实时显示请求摘要，彩色区分状态 | 默认启用 |

### 记录内容

每次请求完整记录：

- **请求信息**：方法、URL、请求头、请求体
- **响应信息**：状态码、响应头、响应体
- **元数据**：时间戳、耗时、响应大小、是否流式传输
- **错误信息**：连接失败、超时等异常

### 敏感信息处理

Dashboard 自动识别并脱敏敏感请求头：

- 认证相关：`Authorization`、`X-API-Key`、`Token`、`Cookie` 等
- 脱敏方式：默认隐藏，点击可查看原文
- 标识显示：敏感字段名称后显示 🔒 图标

## 快速开始

### 安装运行

```bash
# 克隆项目
git clone <repo-url>
cd http-proxy

# 启动服务器
python proxy_server.py
```

启动后：
- 代理服务：`http://127.0.0.1:12345`
- Dashboard：`http://127.0.0.1:3420`

### 使用代理

在目标 URL 前添加代理地址：

```bash
# HTTP 请求
curl "http://127.0.0.1:12345/http://httpbin.org/ip"

# HTTPS 请求
curl "http://127.0.0.1:12345/https://httpbin.org/ip"

# 带认证头的请求
curl -H "Authorization: Bearer token123" \
     "http://127.0.0.1:12345/https://httpbin.org/get"

# POST 请求
curl -X POST -d '{"name":"test"}' \
     "http://127.0.0.1:12345/https://httpbin.org/post"
```

所有请求自动记录到数据库，可在 Dashboard 中查看。

## Dashboard 看板

访问 `http://127.0.0.1:3420` 查看 Web 界面：

### 请求列表（左侧）

- 按时间倒序显示最近请求
- 显示：时间、方法、URL、状态码、大小、耗时
- 支持 `STREAMING`、`ERROR` 标签

### 请求详情（右侧）

- 完整的请求/响应头和请求/响应体
- 敏感头自动脱敏，点击查看原文
- 支持大响应体（自动压缩存储）

### 筛选功能

- **搜索**：按 URL 关键字搜索
- **方法筛选**：GET、POST、PUT、DELETE、PATCH
- **状态码筛选**：2xx、3xx、4xx、5xx

### 数据清理

点击 `Clear` 按钮，支持：

- 按天数清理：清理 N 天前的数据
- 按时间区间：指定起止日期清理

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-p, --port` | 代理服务器端口 | 12345 |
| `--no-web` | 禁用 Dashboard 看板 | - |
| `--web-host` | Dashboard 绑定地址 | 127.0.0.1 |
| `--web-port` | Dashboard 看板端口 | 3420 |
| `--enable-log-file` | 启用日志文件输出 | 默认关闭 |
| `--log-file` | 日志文件路径 | logs/proxy.log |
| `--db-file` | 数据库文件路径 | data/proxy.db |
| `--no-color` | 禁用终端颜色输出 | - |

### 使用示例

```bash
# 基础启动
python proxy_server.py

# Dashboard 对外开放
python proxy_server.py --web-host 0.0.0.0 --web-port 8080

# 启用日志文件（同时保存到数据库）
python proxy_server.py --enable-log-file

# 仅代理功能，无 Dashboard
python proxy_server.py --no-web

# 自定义端口和数据存储
python proxy_server.py -p 8080 --db-file /var/data/proxy.db
```

## API 接口

通过 REST API 查询和管理日志数据：

```bash
# 获取请求列表
curl "http://127.0.0.1:3420/api/requests?limit=50&method=POST&status=2xx&search=httpbin"

# 获取请求详情
curl "http://127.0.0.1:3420/api/requests/abc12345"

# 获取统计信息
curl "http://127.0.0.1:3420/api/stats"

# 清理数据
curl -X DELETE "http://127.0.0.1:3420/api/requests?days=7"
curl -X DELETE "http://127.0.0.1:3420/api/requests?start=2024-01-01&end=2024-01-31"
```

### API 参数说明

| 接口 | 参数 | 说明 |
|-----|------|------|
| `GET /api/requests` | `limit` | 返回数量，默认 100 |
| | `offset` | 偏移量，用于分页 |
| | `method` | 按方法筛选 |
| | `status` | 按状态码筛选 (2xx/3xx/4xx/5xx) |
| | `search` | 按关键字搜索 |
| `DELETE /api/requests` | `days` | 清理 N 天前的数据 |
| | `start` | 开始时间 |
| | `end` | 结束时间 |

## 日志输出格式

### 终端输出

```
时间 方法 URL 状态码 响应大小 耗时
```

示例：
```
22:10:15 GET https://httpbin.org/ip 200 45.0B 1.23s
22:10:16 POST https://httpbin.org/post 200 512.0B 0.89s
22:10:17 [STREAMING] GET https://api.example.com/events 200 1.2KB 5.00s
22:10:18 [ERROR] GET https://example.com/notfound 404 128.0B 0.15s
```

颜色说明：
- 🟢 绿色：成功 (2xx)
- 🟡 黄色：重定向 (3xx) 或流式响应
- 🔴 红色：错误 (4xx, 5xx)

### 日志文件格式（启用时）

```
════════════════════════════════════════════════════════════
[2024-03-14 22:10:15] REQUEST [abc12345]
────────────────────────────────────────────────────────────
GET https://httpbin.org/ip
────────────────────────────────────────────────────────────
Headers:
  User-Agent: curl/7.88.1
  Accept: */*

Body:
  (empty)
════════════════════════════════════════════════════════════
[2024-03-14 22:10:15] RESPONSE
────────────────────────────────────────────────────────────
Status: 200 OK
────────────────────────────────────────────────────────────
Headers:
  Content-Type: application/json
  Content-Length: 45

Body:
  {
    "origin": "1.2.3.4"
  }
════════════════════════════════════════════════════════════
Duration: 1.23s
════════════════════════════════════════════════════════════
```

## 其他功能

### 流式响应支持

自动检测并实时转发流式响应：

- **SSE**：`Content-Type: text/event-stream`
- **Chunked**：`Transfer-Encoding: chunked`
- **NDJSON**：`Content-Type: application/x-ndjson`

流式响应缓存前 64KB 用于日志记录。

### 大数据处理

- 响应体 > 100KB 自动 GZIP 压缩存储
- 二进制数据 Base64 编码存储
- Dashboard 自动解码显示

## 目录结构

```
http-proxy/
├── proxy_server.py       # 主程序入口
├── utils/                # 工具模块
│   ├── colors.py         # 终端颜色
│   └── format.py         # 格式化工具
├── core/                 # 核心模块
│   ├── database.py       # 数据库管理
│   ├── logger.py         # 日志记录
│   └── handlers.py       # 请求处理器
├── dashboard/            # Dashboard 模块
│   ├── server.py         # Dashboard 服务器
│   ├── handler.py        # API 处理
│   └── templates.py      # HTML 模板
├── data/
│   └── proxy.db          # SQLite 数据库
└── logs/
    └── proxy.log         # 日志文件（启用时）
```

## 技术栈

- **语言**：Python 3
- **标准库**：`http.server`、`http.client`、`socketserver`、`threading`、`ssl`、`sqlite3`
- **并发模型**：ThreadingMixIn 多线程
- **存储**：SQLite + GZIP 压缩

## License

MIT