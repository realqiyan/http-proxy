"""Dashboard HTML 模板"""

DASHBOARD_HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HTTP Proxy Dashboard</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header {
            background: #161b22;
            padding: 12px 20px;
            border-bottom: 1px solid #30363d;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .header h1 { font-size: 18px; color: #58a6ff; }
        .stats { display: flex; gap: 20px; font-size: 13px; }
        .stat { display: flex; align-items: center; gap: 6px; }
        .stat-value { color: #58a6ff; font-weight: 600; }
        .container { display: flex; flex: 1; overflow: hidden; }
        .left-panel {
            width: 420px;
            border-right: 1px solid #30363d;
            display: flex;
            flex-direction: column;
            background: #0d1117;
        }
        .right-panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .toolbar {
            padding: 10px;
            background: #161b22;
            border-bottom: 1px solid #30363d;
            display: flex;
            gap: 10px;
        }
        .search-input {
            flex: 1;
            padding: 8px 12px;
            border: 1px solid #30363d;
            border-radius: 6px;
            background: #0d1117;
            color: #c9d1d9;
            font-size: 13px;
        }
        .search-input:focus { outline: none; border-color: #58a6ff; }
        select, button {
            padding: 8px 12px;
            border: 1px solid #30363d;
            border-radius: 6px;
            background: #21262d;
            color: #c9d1d9;
            font-size: 13px;
            cursor: pointer;
        }
        select:hover, button:hover { background: #30363d; }
        .request-list {
            flex: 1;
            overflow-y: auto;
        }
        .request-item {
            padding: 10px 14px;
            border-bottom: 1px solid #21262d;
            cursor: pointer;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 12px;
            transition: background 0.15s;
        }
        .request-item:hover { background: #161b22; }
        .request-item.selected { background: #1f6feb33; border-left: 3px solid #58a6ff; }
        .request-time { color: #8b949e; margin-right: 8px; }
        .request-method { font-weight: 600; margin-right: 8px; }
        .method-GET { color: #3fb950; }
        .method-POST { color: #58a6ff; }
        .method-PUT { color: #d29922; }
        .method-DELETE { color: #f85149; }
        .method-PATCH { color: #a371f7; }
        .request-status { margin-right: 8px; }
        .status-2xx { color: #3fb950; }
        .status-3xx { color: #d29922; }
        .status-4xx, .status-5xx { color: #f85149; }
        .request-url { color: #c9d1d9; word-break: break-all; }
        .request-meta { display: flex; gap: 10px; margin-top: 4px; font-size: 11px; color: #8b949e; }
        .detail-header {
            padding: 14px 18px;
            background: #161b22;
            border-bottom: 1px solid #30363d;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .detail-tabs {
            display: flex;
            background: #161b22;
            border-bottom: 1px solid #30363d;
        }
        .detail-tab {
            padding: 10px 18px;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            color: #8b949e;
            font-size: 13px;
        }
        .detail-tab:hover { color: #c9d1d9; }
        .detail-tab.active { color: #c9d1d9; border-bottom-color: #58a6ff; }
        .detail-content {
            flex: 1;
            overflow: auto;
            padding: 16px;
            background: #0d1117;
        }
        .detail-section { margin-bottom: 20px; }
        .detail-section h3 {
            color: #8b949e;
            font-size: 12px;
            text-transform: uppercase;
            margin-bottom: 10px;
            letter-spacing: 0.5px;
        }
        .detail-row {
            display: flex;
            padding: 6px 0;
            border-bottom: 1px solid #21262d;
            font-size: 13px;
        }
        .detail-key {
            width: 200px;
            color: #79c0ff;
            flex-shrink: 0;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 12px;
        }
        .detail-value {
            color: #c9d1d9;
            word-break: break-all;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 12px;
        }
        .body-content {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 12px;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 12px;
            white-space: pre-wrap;
            word-break: break-all;
            max-height: 500px;
            overflow: auto;
        }
        .empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: #8b949e;
        }
        .empty-state svg { width: 64px; height: 64px; margin-bottom: 16px; opacity: 0.5; }
        .badge {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
        }
        .badge-streaming { background: #d29922; color: #000; }
        .badge-error { background: #f85149; color: #fff; }
        .auto-refresh { display: flex; align-items: center; gap: 8px; }
        .auto-refresh input { width: 16px; height: 16px; }
        .loading { text-align: center; padding: 20px; color: #8b949e; }
        .btn-clear {
            background: #da3633;
            border-color: #f85149;
            margin-left: 12px;
        }
        .btn-clear:hover { background: #f85149; }
        .modal-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.7);
            z-index: 100;
            align-items: center;
            justify-content: center;
        }
        .modal-overlay.show { display: flex; }
        .modal {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 20px;
            width: 400px;
            max-width: 90%;
        }
        .modal h2 { font-size: 16px; margin-bottom: 16px; color: #c9d1d9; }
        .modal-row { margin-bottom: 12px; }
        .modal-row label { display: block; font-size: 13px; color: #8b949e; margin-bottom: 4px; }
        .modal-row input { width: 100%; padding: 8px 12px; border: 1px solid #30363d; border-radius: 6px; background: #0d1117; color: #c9d1d9; font-size: 13px; }
        .modal-row input:focus { outline: none; border-color: #58a6ff; }
        .modal-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px; }
        .modal-actions button { min-width: 80px; }
        .btn-cancel { background: #21262d; }
        .btn-danger { background: #da3633; border-color: #f85149; }
        .btn-danger:hover { background: #f85149; }
        .clear-options { margin-bottom: 16px; }
        .clear-option { padding: 10px; border: 1px solid #30363d; border-radius: 6px; margin-bottom: 8px; cursor: pointer; transition: background 0.15s; }
        .clear-option:hover { background: #21262d; }
        .clear-option.selected { border-color: #58a6ff; background: #1f6feb22; }
        .clear-option-title { font-size: 13px; color: #c9d1d9; margin-bottom: 4px; }
        .clear-option-desc { font-size: 12px; color: #8b949e; }
        .sensitive-value {
            cursor: pointer;
            background: #21262d;
            padding: 2px 6px;
            border-radius: 4px;
            transition: background 0.15s;
        }
        .sensitive-value:hover { background: #30363d; }
        .body-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .body-header h3 { margin: 0; }
        .btn-copy {
            padding: 4px 10px;
            font-size: 11px;
            background: #21262d;
            border: 1px solid #30363d;
            border-radius: 4px;
            color: #8b949e;
            cursor: pointer;
        }
        .btn-copy:hover { background: #30363d; color: #c9d1d9; }
        .json-key { color: #79c0ff; }
        .json-string { color: #a5d6ff; }
        .json-number { color: #79c0ff; }
        .json-boolean { color: #ff7b72; }
        .json-null { color: #8b949e; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔍 HTTP Proxy Dashboard</h1>
        <div class="stats">
            <div class="stat">Total: <span class="stat-value" id="stat-total">0</span></div>
            <div class="stat">Success: <span class="stat-value" id="stat-success">0</span></div>
            <div class="stat">Errors: <span class="stat-value" id="stat-errors">0</span></div>
            <div class="stat">Avg: <span class="stat-value" id="stat-avg">0</span>ms</div>
            <button class="btn-clear" onclick="showClearModal()">🗑️ Clear</button>
        </div>
    </div>
    <div class="container">
        <div class="left-panel">
            <div class="toolbar">
                <input type="text" class="search-input" id="search" placeholder="Search URL...">
                <select id="filter-method">
                    <option value="">All Methods</option>
                    <option value="GET">GET</option>
                    <option value="POST">POST</option>
                    <option value="PUT">PUT</option>
                    <option value="DELETE">DELETE</option>
                    <option value="PATCH">PATCH</option>
                </select>
                <select id="filter-status">
                    <option value="">All Status</option>
                    <option value="2xx">2xx</option>
                    <option value="3xx">3xx</option>
                    <option value="4xx">4xx</option>
                    <option value="5xx">5xx</option>
                </select>
                <div class="auto-refresh">
                    <input type="checkbox" id="auto-refresh" checked>
                    <label for="auto-refresh">Auto</label>
                </div>
            </div>
            <div class="request-list" id="request-list">
                <div class="loading">Loading...</div>
            </div>
        </div>
        <div class="right-panel">
            <div id="detail-view" class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M9 12h6m-3-3v6m-7 4h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                </svg>
                <p>Select a request to view details</p>
            </div>
        </div>
    </div>

    <!-- Clear Modal -->
    <div class="modal-overlay" id="clear-modal">
        <div class="modal">
            <h2>🗑️ 清理请求数据</h2>
            <div class="clear-options">
                <div class="clear-option selected" data-type="days" onclick="selectClearType('days')">
                    <div class="clear-option-title">按天数清理</div>
                    <div class="clear-option-desc">清理 N 天前的所有数据</div>
                </div>
                <div class="clear-option" data-type="range" onclick="selectClearType('range')">
                    <div class="clear-option-title">按时间区间清理</div>
                    <div class="clear-option-desc">清理指定起止时间的数据</div>
                </div>
            </div>
            <div id="clear-days-option">
                <div class="modal-row">
                    <label>清理多少天前的数据</label>
                    <input type="number" id="clear-days" value="7" min="1" max="365">
                </div>
            </div>
            <div id="clear-range-option" style="display:none">
                <div class="modal-row">
                    <label>开始时间</label>
                    <input type="date" id="clear-start">
                </div>
                <div class="modal-row">
                    <label>结束时间</label>
                    <input type="date" id="clear-end">
                </div>
            </div>
            <div class="modal-actions">
                <button class="btn-cancel" onclick="hideClearModal()">取消</button>
                <button class="btn-danger" onclick="doClear()">确认清理</button>
            </div>
        </div>
    </div>

    <script>
        let selectedId = null;
        let refreshInterval = null;

        // 认证令牌支持
        function getAuthToken() {
            // 从 URL 参数获取
            const params = new URLSearchParams(window.location.search);
            return params.get('token') || localStorage.getItem('auth_token');
        }

        function setAuthToken(token) {
            if (token) {
                localStorage.setItem('auth_token', token);
            }
        }

        function authFetch(url, options = {}) {
            const token = getAuthToken();
            if (token) {
                options.headers = options.headers || {};
                options.headers['Authorization'] = 'Bearer ' + token;
            }
            return fetch(url, options);
        }

        function formatSize(bytes) {
            if (!bytes) return '0B';
            const units = ['B', 'KB', 'MB', 'GB'];
            for (let u of units) {
                if (bytes < 1024) return bytes.toFixed(1) + u;
                bytes /= 1024;
            }
            return bytes.toFixed(1) + 'TB';
        }

        function formatTime(iso) {
            const d = new Date(iso);
            const month = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            const time = d.toTimeString().slice(0, 8);
            return `${month}-${day} ${time}`;
        }

        async function loadStats() {
            try {
                const res = await authFetch('/api/stats');
                if (res.status === 401) {
                    showAuthPrompt();
                    return;
                }
                const data = await res.json();
                document.getElementById('stat-total').textContent = data.total;
                document.getElementById('stat-success').textContent = data.success;
                document.getElementById('stat-errors').textContent = data.errors;
                document.getElementById('stat-avg').textContent = data.avg_duration;
            } catch (e) {}
        }

        async function loadRequests() {
            const search = document.getElementById('search').value;
            const method = document.getElementById('filter-method').value;
            const status = document.getElementById('filter-status').value;

            const params = new URLSearchParams({ limit: 100 });
            if (search) params.append('search', search);
            if (method) params.append('method', method);
            if (status) params.append('status', status);

            try {
                const res = await authFetch('/api/requests?' + params);
                if (res.status === 401) {
                    showAuthPrompt();
                    return;
                }
                const requests = await res.json();

                const list = document.getElementById('request-list');
                if (!requests.length) {
                    list.innerHTML = '<div class="loading">No requests</div>';
                    return;
                }

                list.innerHTML = requests.map(r => `
                    <div class="request-item ${r.id === selectedId ? 'selected' : ''}" data-id="${r.id}">
                        <div>
                            <span class="request-time">${formatTime(r.timestamp)}</span>
                            <span class="request-method method-${r.method}">${r.method}</span>
                            <span class="request-status status-${r.status < 300 ? '2xx' : r.status < 400 ? '3xx' : '4xx'}">${r.status}</span>
                            <span class="request-url">${r.url}</span>
                            ${r.is_streaming ? '<span class="badge badge-streaming">STREAMING</span>' : ''}
                            ${r.error ? '<span class="badge badge-error">ERROR</span>' : ''}
                        </div>
                        <div class="request-meta">
                            <span>${formatSize(r.response_size)}</span>
                            <span>${r.duration_ms.toFixed(1)}ms</span>
                        </div>
                    </div>
                `).join('');

                document.querySelectorAll('.request-item').forEach(item => {
                    item.addEventListener('click', () => selectRequest(item.dataset.id));
                });
            } catch (e) {
                console.error('Load failed:', e);
            }
        }

        async function selectRequest(id) {
            selectedId = id;
            document.querySelectorAll('.request-item').forEach(item => {
                item.classList.toggle('selected', item.dataset.id === id);
            });

            try {
                const res = await authFetch('/api/requests/' + id);
                if (res.status === 401) {
                    showAuthPrompt();
                    return;
                }
                const detail = await res.json();

                if (!detail) return;

                const reqHeaders = detail.request_headers ? JSON.parse(detail.request_headers) : {};
                const respHeaders = detail.response_headers ? JSON.parse(detail.response_headers) : {};
                const reqBody = detail.request_body || '(empty)';
                const respBody = detail.response_body || '(empty)';

                document.getElementById('detail-view').outerHTML = `
                    <div id="detail-view" class="detail-content">
                        <div class="detail-section">
                            <h3>Request</h3>
                            <div class="detail-row">
                                <div class="detail-key">Method</div>
                                <div class="detail-value">${detail.method}</div>
                            </div>
                            <div class="detail-row">
                                <div class="detail-key">URL</div>
                                <div class="detail-value">${detail.url}</div>
                            </div>
                            ${Object.entries(reqHeaders).map(([k, v]) => `
                                <div class="detail-row">
                                    <div class="detail-key">${formatHeaderKey(k)}</div>
                                    <div class="detail-value">${formatHeaderValue(k, v)}</div>
                                </div>
                            `).join('')}
                            <h3 style="margin-top:16px">Request Body</h3>
                            ${renderBody(reqBody, reqHeaders, 'req-body')}
                        </div>
                        <div class="detail-section">
                            <h3>Response</h3>
                            <div class="detail-row">
                                <div class="detail-key">Status</div>
                                <div class="detail-value">${detail.status}</div>
                            </div>
                            ${Object.entries(respHeaders).map(([k, v]) => `
                                <div class="detail-row">
                                    <div class="detail-key">${formatHeaderKey(k)}</div>
                                    <div class="detail-value">${formatHeaderValue(k, v)}</div>
                                </div>
                            `).join('')}
                            <h3 style="margin-top:16px">Response Body</h3>
                            ${renderBody(respBody, respHeaders, 'resp-body')}
                        </div>
                    </div>
                `;

                // 使用 textContent 设置 body 内容，避免 HTML 解析问题
                const reqBodyDiv = document.getElementById('body-req-body');
                const respBodyDiv = document.getElementById('body-resp-body');

                // 监控 div 变化，如果被外部修改则恢复
                const protectContent = (div, originalContent) => {
                    const observer = new MutationObserver(() => {
                        if (div.textContent !== originalContent) {
                            // 延迟恢复，避免无限循环
                            setTimeout(() => {
                                if (div.textContent !== originalContent) {
                                    div.textContent = originalContent;
                                }
                            }, 0);
                        }
                    });
                    observer.observe(div, { childList: true, characterData: true, subtree: true });
                    return observer;
                };

                reqBodyDiv.textContent = reqBody;
                respBodyDiv.textContent = respBody;
                protectContent(reqBodyDiv, reqBody);
                protectContent(respBodyDiv, respBody);
            } catch (e) {
                console.error('Load detail failed:', e);
            }
        }

        function escapeHtml(str) {
            if (!str) return '';
            return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }

        // 敏感头字段列表
        const SENSITIVE_HEADERS = [
            'authorization', 'cookie', 'set-cookie', 'x-api-key', 'api-key',
            'x-auth-token', 'x-access-token', 'x-token', 'token',
            'x-secret', 'secret', 'password', 'passwd',
            'x-api-secret', 'api-secret', 'private-key',
            'x-session-token', 'session-token', 'access-token', 'refresh-token'
        ];

        function isSensitiveHeader(key) {
            const lowerKey = key.toLowerCase();
            for (const sensitive of SENSITIVE_HEADERS) {
                if (lowerKey === sensitive || lowerKey.includes(sensitive)) {
                    return true;
                }
            }
            return false;
        }

        function maskHeader(key, value) {
            if (!value) return value;
            if (isSensitiveHeader(key)) {
                // 模糊处理：只显示前几个字符
                if (value.length <= 8) {
                    return '****';
                }
                return value.substring(0, 4) + '****' + value.substring(value.length - 4);
            }
            return value;
        }

        function formatHeaderKey(key) {
            if (isSensitiveHeader(key)) {
                return key + ' 🔒';
            }
            return key;
        }

        function formatHeaderValue(key, value) {
            const escaped = escapeHtml(value);
            if (isSensitiveHeader(key)) {
                const masked = maskHeader(key, value);
                return `<span class="sensitive-value" data-value="${escaped}" onclick="toggleSensitive(this)">${escapeHtml(masked)}</span>`;
            }
            return escaped;
        }

        function toggleSensitive(el) {
            const current = el.textContent;
            const original = el.dataset.value;
            el.textContent = current === original ? escapeHtml(maskHeader('', original)) : original;
        }

        function copyToClipboard(text, btn) {
            // 使用 textarea fallback 方案（支持非 HTTPS 环境）
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            try {
                document.execCommand('copy');
                const originalText = btn.textContent;
                btn.textContent = 'Copied!';
                btn.style.color = '#3fb950';
                setTimeout(() => {
                    btn.textContent = originalText;
                    btn.style.color = '';
                }, 1500);
            } catch (err) {
                console.error('Copy failed:', err);
            }
            document.body.removeChild(textarea);
        }

        function isJsonContentType(headers) {
            const ct = headers['content-type'] || headers['Content-Type'] || '';
            return ct.toLowerCase().includes('application/json');
        }

        function syntaxHighlightJson(json) {
            return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {
                let cls = 'json-number';
                if (/^"/.test(match)) {
                    if (/:$/.test(match)) {
                        cls = 'json-key';
                    } else {
                        cls = 'json-string';
                    }
                } else if (/true|false/.test(match)) {
                    cls = 'json-boolean';
                } else if (/null/.test(match)) {
                    cls = 'json-null';
                }
                return '<span class="' + cls + '">' + match + '</span>';
            });
        }

        function renderBody(body, headers, bodyId) {
            return `
                <div class="body-header">
                    <h3>Body</h3>
                    <button class="btn-copy" data-body="${encodeURIComponent(body || '')}" onclick="copyBody(this)">Copy</button>
                </div>
                <div class="body-content" id="body-${bodyId}"></div>
            `;
        }

        function copyBody(btn) {
            const raw = decodeURIComponent(btn.getAttribute('data-body'));
            copyToClipboard(raw, btn);
        }

        function escapeJs(str) {
            return str.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$/g, '\\$');
        }

        function setupAutoRefresh() {
            const checkbox = document.getElementById('auto-refresh');
            const toggle = () => {
                if (checkbox.checked) {
                    refreshInterval = setInterval(() => {
                        loadRequests();
                        loadStats();
                    }, 2000);
                } else {
                    clearInterval(refreshInterval);
                }
            };
            checkbox.addEventListener('change', toggle);
            toggle();
        }

        document.getElementById('search').addEventListener('input', loadRequests);
        document.getElementById('filter-method').addEventListener('change', loadRequests);
        document.getElementById('filter-status').addEventListener('change', loadRequests);

        // 认证提示
        function showAuthPrompt() {
            const existing = document.getElementById('auth-modal');
            if (existing) return;

            const modal = document.createElement('div');
            modal.id = 'auth-modal';
            modal.className = 'modal show';
            modal.innerHTML = `
                <div class="modal-content">
                    <h2>认证令牌</h2>
                    <p style="color: #8b949e; margin: 10px 0;">请输入认证令牌以访问 API</p>
                    <input type="text" id="auth-token-input" placeholder="Token" style="width: 100%; padding: 10px; margin: 10px 0; border: 1px solid #30363d; background: #0d1117; color: #c9d1d9; border-radius: 6px;">
                    <div style="display: flex; gap: 10px; justify-content: flex-end;">
                        <button onclick="document.getElementById('auth-modal').remove()" style="padding: 8px 16px; background: #21262d; border: 1px solid #30363d; color: #c9d1d9; border-radius: 6px;">取消</button>
                        <button onclick="submitAuth()" style="padding: 8px 16px; background: #238636; border: none; color: white; border-radius: 6px;">确认</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }

        function submitAuth() {
            const token = document.getElementById('auth-token-input').value;
            if (token) {
                setAuthToken(token);
                document.getElementById('auth-modal').remove();
                loadRequests();
                loadStats();
            }
        }

        loadRequests();
        loadStats();
        setupAutoRefresh();

        // Clear modal functions
        let clearType = 'days';

        function showClearModal() {
            document.getElementById('clear-modal').classList.add('show');
        }

        function hideClearModal() {
            document.getElementById('clear-modal').classList.remove('show');
        }

        function selectClearType(type) {
            clearType = type;
            document.querySelectorAll('.clear-option').forEach(el => {
                el.classList.toggle('selected', el.dataset.type === type);
            });
            document.getElementById('clear-days-option').style.display = type === 'days' ? 'block' : 'none';
            document.getElementById('clear-range-option').style.display = type === 'range' ? 'block' : 'none';
        }

        async function doClear() {
            let url = '/api/requests?';
            if (clearType === 'days') {
                const days = document.getElementById('clear-days').value;
                url += 'days=' + days;
            } else {
                const start = document.getElementById('clear-start').value;
                const end = document.getElementById('clear-end').value;
                if (!start && !end) {
                    alert('请选择时间区间');
                    return;
                }
                if (start) url += 'start=' + start;
                if (end) url += '&end=' + end;
            }

            try {
                const res = await authFetch(url, { method: 'DELETE' });
                if (res.status === 401) {
                    showAuthPrompt();
                    return;
                }
                const data = await res.json();
                if (data.success) {
                    alert(data.message);
                    hideClearModal();
                    loadRequests();
                    loadStats();
                } else {
                    alert('清理失败: ' + data.error);
                }
            } catch (e) {
                alert('请求失败: ' + e.message);
            }
        }

        // Close modal on overlay click
        document.getElementById('clear-modal').addEventListener('click', (e) => {
            if (e.target.id === 'clear-modal') hideClearModal();
        });
    </script>
</body>
</html>
'''