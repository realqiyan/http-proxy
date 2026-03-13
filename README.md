# HTTP Forwarding Server

一个轻量级的 HTTP 转发服务器，通过 URL 前缀方式转发请求，并提供 Web Dashboard 看板。

## 使用方式

在目标 URL 前添加代理服务器地址：

```
http://127.0.0.1:12345/http://httpbin.org/ip
http://127.0.0.1:12345/https://httpbin.org/ip
```

即：`http://代理服务器地址/http://目标地址` 或 `http://代理服务器地址/https://目标地址`

## 快速开始

```bash
# 启动服务器（默认代理端口 12345，Dashboard 端口 3420）
python proxy_server.py

# 指定端口
python proxy_server.py -p 8080 --web-port 9090

# 禁用 Dashboard
python proxy_server.py --no-web

# Dashboard 对外开放
python proxy_server.py --web-host 0.0.0.0

# 禁用颜色输出
python proxy_server.py --no-color

# 指定日志文件和数据库
python proxy_server.py --log-file /var/log/proxy.log --db-file /var/data/proxy.db
```

## Dashboard 看板

启动服务器后，访问 http://127.0.0.1:3420 查看 Web 看板：

- **左侧面板**：请求列表，按时间倒序展示
- **右侧面板**：点击请求查看完整的请求/响应详情
- **搜索过滤**：支持按 URL、方法、状态码筛选
- **自动刷新**：每 2 秒自动更新列表
- **统计信息**：显示总请求数、成功数、错误数、平均耗时

## 测试示例

```bash
# HTTP 请求
curl "http://127.0.0.1:12345/http://httpbin.org/ip"

# HTTPS 请求
curl "http://127.0.0.1:12345/https://httpbin.org/ip"

# 带查询参数
curl "http://127.0.0.1:12345/https://httpbin.org/get?foo=bar"

# POST 请求
curl -X POST -d "name=test" "http://127.0.0.1:12345/https://httpbin.org/post"

# 指定端口的目标服务器
curl "http://127.0.0.1:12345/http://example.com:8080/api"
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-p, --port` | 代理服务器端口 | 12345 |
| `--no-web` | 禁用 Dashboard 看板 | - |
| `--web-host` | Dashboard 绑定地址 | 127.0.0.1 |
| `--web-port` | Dashboard 看板端口 | 3420 |
| `--no-color` | 禁用颜色输出 | - |
| `--log-file` | 日志文件路径 | logs/proxy.log |
| `--enable-log-file` | 启用日志文件输出 | 默认关闭 |
| `--db-file` | SQLite 数据库路径 | data/proxy.db |

## 功能特性

- **HTTP/HTTPS 转发** - 支持 HTTP 和 HTTPS 目标服务器
- **流式传输** - 支持 chunked encoding 和大文件传输
- **流式响应处理** - 自动检测 SSE/流式响应并实时转发
- **并发处理** - 多线程处理多个并发请求
- **完整日志** - 同时输出到终端、日志文件和数据库
- **Web Dashboard** - 提供可视化的请求查看界面
- **数据持久化** - SQLite 数据库存储请求历史
- **彩色输出** - 终端日志使用颜色区分不同状态
- **保留请求头** - 转发时保留原始请求头和请求体

## API 接口

Dashboard 提供以下 REST API：

```
GET /api/requests       # 获取请求列表
  参数: limit, offset, method, status, search

GET /api/requests/:id   # 获取请求详情

GET /api/stats          # 获取统计信息

DELETE /api/requests    # 清理请求数据
  参数:
    start: 开始时间 (如 2024-01-01 或 2024-01-01T00:00:00)
    end: 结束时间 (如 2024-01-31 或 2024-01-31T23:59:59)
    days: 清理 N 天前的数据

# 示例
curl "http://127.0.0.1:3420/api/requests?limit=50"
curl -X DELETE "http://127.0.0.1:3420/api/requests?start=2024-01-01&end=2024-01-31"
curl -X DELETE "http://127.0.0.1:3420/api/requests?days=7"
```

## 日志格式

终端输出格式：
```
时间 方法 URL 状态码 响应大小 耗时
```

示例输出：
```
22:10:15 GET https://httpbin.org:443/ip 200 45.0B 1.23s
22:10:16 POST https://httpbin.org:443/post 200 512.0B 0.89s
22:10:17 [STREAMING] GET https://api.example.com/events 200 1.2KB 5.00s
```

颜色说明：
- 绿色：成功状态码 (2xx)
- 黄色：重定向状态码 (3xx) 或流式响应
- 红色：错误状态码 (4xx, 5xx)
- 蓝色：耗时
- 紫色：响应大小

## 目录结构

```
http-proxy/
├── proxy_server.py       # 主程序入口
├── README.md             # 说明文档
├── utils/                # 工具模块
│   ├── __init__.py
│   ├── colors.py         # 终端颜色
│   └── format.py         # 格式化工具
├── core/                 # 核心模块
│   ├── __init__.py
│   ├── database.py       # 数据库管理
│   ├── logger.py         # 日志记录
│   └── handlers.py       # 请求处理器
├── dashboard/            # Dashboard 模块
│   ├── __init__.py
│   ├── server.py         # Dashboard 服务器
│   ├── handler.py        # Dashboard 请求处理
│   └── templates.py      # HTML 模板
├── logs/
│   └── proxy.log         # 日志文件
└── data/
    └── proxy.db          # SQLite 数据库
```

## 技术实现

- **语言**: Python 3
- **标准库**: `http.server`, `http.client`, `socketserver`, `threading`, `ssl`, `sqlite3`
- **并发模型**: ThreadingMixIn 多线程模型
- **HTTPS 支持**: 通过 ssl 模块建立安全连接
- **流式传输**: 分块读取和转发，支持大文件和 SSE
- **数据存储**: SQLite 数据库，支持压缩大文本

## 流式响应处理

服务器自动检测并处理流式响应：

- **Server-Sent Events (SSE)**: `Content-Type: text/event-stream`
- **Chunked Encoding**: `Transfer-Encoding: chunked`
- **NDJSON**: `Content-Type: application/x-ndjson`

对于流式响应，服务器会：
1. 实时转发数据给客户端
2. 缓存前 64KB 用于日志记录
3. 标记请求为"流式"在 Dashboard 中显示

## 注意事项

1. 数据库会持久化存储请求，建议定期清理旧数据
2. 默认连接超时为 60 秒
3. 支持 HTTP/1.1 协议
4. 大响应体（>100KB）会自动压缩存储

## License

MIT