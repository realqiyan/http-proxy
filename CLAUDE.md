# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HTTP Proxy Logger - A lightweight HTTP forwarding server focused on request/response logging with a web dashboard. It uses URL prefix routing: `http://proxy:12345/http://target.com`

## Commands

```bash
# Start service (daemon mode with auto-restart)
python proxy_server.py

# Stop service
python proxy_server.py stop

# Check status
python proxy_server.py status

# Install as Linux systemd service (requires sudo)
sudo python proxy_server.py install

# Uninstall systemd service
sudo python proxy_server.py uninstall
```

## Architecture

```
proxy_server.py          # Entry point: CLI parsing, daemon management, systemd service
├── core/
│   ├── handlers.py      # ForwardingHandler: HTTP proxy logic, streaming support, retries
│   ├── database.py      # DatabaseManager: SQLite persistence, GZIP compression for large bodies
│   └── logger.py        # RequestLogger: logs to file and database
├── dashboard/
│   ├── server.py        # DashboardServer: ThreadingMixIn TCP server
│   ├── handler.py       # DashboardHandler: REST API endpoints
│   └── templates.py     # Embedded HTML/CSS/JS (single file)
└── utils/
    ├── colors.py        # Terminal ANSI colors
    └── format.py        # format_size, format_duration, format_body
```

## Key Design Decisions

1. **URL Prefix Proxy**: Target URL is extracted from path after `/http://` or `/https://`
2. **Dual Server Architecture**: Proxy (port 12345) and Dashboard (port 3420) run as separate threads
3. **Streaming Detection**: `ForwardingHandler._is_streaming_response()` checks Content-Type and Transfer-Encoding
4. **Sensitive Header Masking**: Dashboard masks auth headers (Authorization, Cookie, X-API-Key, etc.) - click to reveal
5. **Config Persistence**: Only non-default values saved to `~/.http-proxy/config.json`
6. **Body Compression**: Responses >100KB are GZIP compressed in SQLite

## Data Storage

All data in `~/.http-proxy/`:
- `config.json` - Startup config (only non-default values)
- `proxy.pid` - Process ID for daemon management
- `data/proxy.db` - SQLite with tables: `requests`, `request_details`
- `logs/proxy.log` - Text logs (when `--enable-log-file`)

## Database Schema

```sql
requests (id, timestamp, method, url, host, path, status, duration_ms, request_size, response_size, is_streaming, error)
request_details (request_id, request_headers, request_body, response_headers, response_body)
```

## API Endpoints

Dashboard on port 3420:
- `GET /api/requests` - List requests (params: limit, offset, method, status, search)
- `GET /api/requests/:id` - Request detail
- `GET /api/stats` - Statistics
- `DELETE /api/requests` - Clear data (params: days, start, end)