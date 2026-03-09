# HTTP Forwarding Server

一个轻量级的 HTTP 转发服务器，通过 URL 前缀方式转发请求。

## 使用方式

在目标 URL 前添加代理服务器地址：

```
http://127.0.0.1:12345/http://httpbin.org/ip
http://127.0.0.1:12345/https://httpbin.org/ip
```

即：`http://代理服务器地址/http://目标地址` 或 `http://代理服务器地址/https://目标地址`

## 快速开始

```bash
# 启动服务器（默认端口 12345）
python proxy_server.py

# 指定端口
python proxy_server.py -p 8080

# 禁用颜色输出
python proxy_server.py --no-color

# 指定日志文件
python proxy_server.py --log-file /var/log/proxy.log
```

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
| `-p, --port` | 服务器端口 | 12345 |
| `--no-color` | 禁用颜色输出 | - |
| `--log-file` | 日志文件路径 | logs/proxy.log |

## 功能特性

- ✅ **HTTP/HTTPS 转发** - 支持 HTTP 和 HTTPS 目标服务器
- ✅ **流式传输** - 支持 chunked encoding 和大文件传输
- ✅ **并发处理** - 多线程处理多个并发请求
- ✅ **完整日志** - 同时输出到终端和日志文件
- ✅ **彩色输出** - 终端日志使用颜色区分不同状态
- ✅ **保留请求头** - 转发时保留原始请求头和请求体

## 日志格式

```
时间 方法 URL 状态码 响应大小 耗时
```

示例输出：
```
22:10:15 GET https://httpbin.org:443/ip 200 45.0B 1.23s
22:10:16 POST https://httpbin.org:443/post 200 512.0B 0.89s
22:10:17 GET http://example.com:80/notfound 404 0.0B 0.05s
```

颜色说明：
- 🟢 绿色：成功状态码 (2xx)
- 🟡 黄色：重定向状态码 (3xx)
- 🔴 红色：错误状态码 (4xx, 5xx)
- 🔵 蓝色：耗时
- 🟣 紫色：响应大小

## 目录结构

```
http-proxy/
├── proxy_server.py    # 主程序
├── README.md          # 说明文档
└── logs/
    └── proxy.log      # 日志文件（自动创建）
```

## 技术实现

- **语言**: Python 3
- **标准库**: `http.server`, `http.client`, `socketserver`, `threading`, `ssl`
- **并发模型**: ThreadingMixIn 多线程模型
- **HTTPS 支持**: 通过 ssl 模块建立安全连接
- **流式传输**: 分块读取和转发，支持大文件

## 注意事项

1. 日志文件会持续追加，建议定期清理
2. 默认连接超时为 30 秒
3. 支持 HTTP/1.1 协议

## License

MIT