"""lm-mem 只读 Web 记忆台。

基于标准库 http.server,零额外依赖。仅本机访问、只读,用于在浏览器里
查看/检索已保存的记忆,不会改动任何数据。

启动:
    uv run python -m web.py or LM_MEM_WEB_PORT=8080 uv run python web.py
    # 默认 http://127.0.0.1:7531

路由:
    /                  列表(支持 ?user_id=&agent_id=&app_id=&run_id=&q=)
    /search?q=...      语义检索
    /mem/<id>          单条详情
    /stats             统计
    /api/...           上述各页面的 JSON 版本
"""

from __future__ import annotations

import html
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import db as _db

# 为避免与 helpers 命名冲突(都有 _SCOPE_KEYS 等),建短别名。
import helpers as _hlp
from mcp_tools import memory_stats as _stats_fn

_HOST = "127.0.0.1"
_PORT = 7531

_PAGE_CSS = """
body{font:14px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;color:#222;
     background:#fafafa}
.wrap{max-width:980px;margin:0 auto;padding:20px}
h1{font-size:18px;margin:0 0 16px}
h2{font-size:15px;margin:24px 0 8px}
.nav{display:flex;gap:14px;margin-bottom:16px;border-bottom:1px solid #e2e2e2;padding-bottom:8px}
.nav a{text-decoration:none;color:#0366d6}
form{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}
input,button{font:inherit;padding:5px 9px;border:1px solid #ccc;border-radius:4px}
button{background:#0366d6;color:#fff;border-color:#0366d6;cursor:pointer}
input[type=text]{flex:1;min-width:200px}
.card{background:#fff;border:1px solid #e6e6e6;border-radius:6px;padding:12px 16px;
      margin-bottom:10px}
.card .id{color:#888;font-size:12px;font-family:ui-monospace,monospace}
.card .sim{color:#0a7d28;font-size:12px}
.card .meta{color:#666;font-size:12px;margin-top:4px}
.card .content{margin:6px 0;white-space:pre-wrap;word-break:break-word}
.muted{color:#888}
table{border-collapse:collapse;width:100%;background:#fff}
td,th{border:1px solid #e6e6e6;padding:6px 10px;text-align:left;font-size:13px}
th{background:#f0f0f0}
pre{background:#fff;border:1px solid #e6e6e6;border-radius:6px;padding:12px;
    white-space:pre-wrap;word-break:break-word;overflow:auto}
"""


def _fmt_ts(ts):
    if not ts:
        return "-"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except Exception:
        return str(ts)


def _record(mem_id, doc, meta):
    """把一条记忆整理成可序列化的 dict。"""
    meta = meta or {}
    rec = {
        "id": mem_id,
        "content": doc,
        "tags": meta.get("tags", "") or "",
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "expires_at": meta.get("expires_at"),
        "scope": {k: meta[k] for k in _hlp._SCOPE_KEYS if meta.get(k)},
        "metadata": _hlp._user_metadata(meta),
    }
    return rec


def _list_records(user_id="", agent_id="", app_id="", run_id=""):
    where = _hlp._scope_where(user_id, agent_id, app_id, run_id)
    res = _db._collection.get(
        where=where, include=["documents", "metadatas"]
    )
    now = time.time()
    records = []
    for mem_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"]):
        if _hlp._is_expired(meta, now):
            continue
        records.append(_record(mem_id, doc, meta))
    # 新创建的靠前
    records.sort(key=lambda r: r["created_at"] or 0, reverse=True)
    return records


def _search_records(query, user_id="", agent_id="", app_id="", run_id="", limit=20):
    if _db._collection.count() == 0:
        return []
    clauses = _hlp._clauses(user_id, agent_id, app_id, run_id)
    where = _hlp._combine(clauses)
    n = min(_db._collection.count(), max(limit * _hlp._OVERFETCH, limit + 10))
    res = _db._collection.query(query_texts=[query], n_results=n, where=where)
    now = time.time()
    out = []
    if not res["ids"] or not res["ids"][0]:
        return out
    for mem_id, doc, meta, dist in zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        if _hlp._is_expired(meta, now):
            continue
        rec = _record(mem_id, doc, meta)
        rec["similarity"] = round(1 - dist, 3)
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def _stats_text(user_id="", agent_id="", app_id="", run_id=""):
    return _stats_fn(user_id, agent_id, app_id, run_id)


def _esc(s):
    return html.escape(str(s) if s is not None else "")


def _render_list(records, scope_vals, q=""):
    q_field = f'<input type="text" name="q" value="{_esc(q)}" placeholder="关键词(留空则按作用域列出)">'
    scope_fields = "".join(
        f'<input type="text" name="{k}" value="{_esc(scope_vals.get(k, ""))}" placeholder="{k}">'
        for k in _hlp._SCOPE_KEYS
    )
    cards = []
    for r in records:
        scope = " ".join(f"{k}={_esc(v)}" for k, v in r["scope"].items())
        meta_bits = []
        if r["tags"]:
            meta_bits.append(f"tags: {_esc(r['tags'])}")
        if scope:
            meta_bits.append(_esc(scope))
        if r["expires_at"]:
            meta_bits.append(f"过期: {_esc(_fmt_ts(r['expires_at']))}")
        cards.append(
            f'<div class="card">'
            f'<div class="id"><a href="/mem/{_esc(r["id"])}">{_esc(r["id"])}</a></div>'
            f'<div class="content">{_esc(r["content"])}</div>'
            f'<div class="meta">{ " · ".join(meta_bits) }</div>'
            f"</div>"
        )
    body = "".join(cards) or '<p class="muted">没有匹配的记忆。</p>'
    return _page("记忆台", f"""
        <div class="nav">
          <a href="/">列表</a>
          <a href="/stats">统计</a>
        </div>
        <form method="get" action="/">
          {scope_fields}
          {q_field}
          <button type="submit">查看</button>
        </form>
        <p class="muted">共 {len(records)} 条有效记忆。</p>
        {body}
    """)


def _render_detail(rec):
    if not rec:
        return _page("未找到", '<p class="muted">没有这条记忆。</p>')
    pre = html.escape(json.dumps(rec, ensure_ascii=False, indent=2))
    scope = " ".join(f"{k}={_esc(v)}" for k, v in rec["scope"].items()) or "-"
    return _page(f"记忆 {rec['id'][:8]}", f"""
        <div class="nav"><a href="/">← 返回列表</a></div>
        <div class="card">
          <div class="id">{_esc(rec["id"])}</div>
          <div class="content">{_esc(rec["content"])}</div>
          <div class="meta">
            tags: {_esc(rec["tags"] or "-")} · 作用域: {_esc(scope)}<br>
            创建: {_esc(_fmt_ts(rec["created_at"]))} ·
            更新: {_esc(_fmt_ts(rec["updated_at"]))} ·
            过期: {_esc(_fmt_ts(rec["expires_at"]))}
          </div>
        </div>
        <h2>原始数据</h2>
        <pre>{pre}</pre>
    """)


def _render_search(records, q):
    rows = "".join(
        f'<tr><td>{r["similarity"]:.2f}</td>'
        f'<td><a href="/mem/{_esc(r["id"])}">{_esc(r["content"][:60])}</a></td>'
        f'<td>{_esc(" ".join(f"{k}={v}" for k,v in r["scope"].items()))}</td></tr>'
        for r in records
    ) or '<tr><td colspan="3" class="muted">没有匹配的记忆。</td></tr>'
    return _page(f"搜索: {q}", f"""
        <div class="nav"><a href="/">← 返回列表</a></div>
        <form method="get" action="/search">
          <input type="text" name="q" value="{_esc(q)}" placeholder="语义检索关键词">
          <button type="submit">搜索</button>
        </form>
        <table><thead><tr><th>相似度</th><th>内容</th><th>作用域</th></tr></thead>
        <tbody>{rows}</tbody></table>
    """)


def _render_stats(text):
    return _page("统计", f"""
        <div class="nav"><a href="/">← 返回列表</a></div>
        <pre>{_esc(text)}</pre>
    """)


def _page(title, body):
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_esc(title)}</title><style>{_PAGE_CSS}</style></head>"
        f"<body><div class='wrap'><h1>🧠 lm-mem 记忆台</h1>{body}</div></body></html>"
    )


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默默认日志
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _scope_from_qs(self, qs):
        return {k: (qs.get(k, [""])[0]) for k in _hlp._SCOPE_KEYS}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        try:
            if path == "/api/list" or path == "/":
                sv = self._scope_from_qs(qs)
                q = qs.get("q", [""])[0].strip()
                records = (_search_records(q, **sv) if q
                           else _list_records(**sv))
                if path == "/api/list":
                    return self._send(200, json.dumps(records, ensure_ascii=False),
                                      "application/json; charset=utf-8")
                return self._send(200, _render_list(records, sv, q))

            if path == "/api/search":
                q = qs.get("q", [""])[0].strip()
                sv = self._scope_from_qs(qs)
                return self._send(
                    200, json.dumps(_search_records(q, **sv), ensure_ascii=False),
                    "application/json; charset=utf-8")

            if path == "/search":
                q = qs.get("q", [""])[0].strip()
                sv = self._scope_from_qs(qs)
                return self._send(200, _render_search(_search_records(q, **sv), q))

            if path.startswith("/api/mem/"):
                mid = path[len("/api/mem/"):]
                return self._send(200, json.dumps(_get_one(mid), ensure_ascii=False),
                                  "application/json; charset=utf-8")

            if path.startswith("/mem/"):
                mid = path[len("/mem/"):]
                return self._send(200, _render_detail(_get_one(mid)))

            if path in ("/stats", "/api/stats"):
                sv = self._scope_from_qs(qs)
                text = _stats_text(**sv)
                if path == "/api/stats":
                    return self._send(200, json.dumps({"stats": text}, ensure_ascii=False),
                                      "application/json; charset=utf-8")
                return self._send(200, _render_stats(text))

            return self._send(404, _page("404", '<p class="muted">没有这个页面。</p>'))
        except Exception as exc:  # noqa: BLE001
            return self._send(500, _page("出错", f"<pre>{_esc(exc)}</pre>"))


def _get_one(mem_id):
    res = _db._collection.get(ids=[mem_id], include=["documents", "metadatas"])
    if not res["ids"]:
        return None
    if _hlp._is_expired(res["metadatas"][0]):
        return None
    return _record(res["ids"][0], res["documents"][0], res["metadatas"][0])


def main() -> None:
    host = os.environ.get("LM_MEM_WEB_HOST", _HOST).strip() or _HOST
    port = int(os.environ.get("LM_MEM_WEB_PORT", str(_PORT)))
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"lm-mem 记忆台: http://{host}:{port}  (只读, Ctrl+C 退出)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        httpd.server_close()


def start_web_thread(host=None, port=None):
    """在后台 daemon 线程启动 Web 台,端口被占则静默跳过(端口抢占单例)。"""
    import threading

    host = (host or os.environ.get("LM_MEM_WEB_HOST", _HOST)).strip() or _HOST
    port = port or int(os.environ.get("LM_MEM_WEB_PORT", str(_PORT)))
    try:
        httpd = ThreadingHTTPServer((host, port), _Handler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        print(f"[lm-mem] Web 记忆台: http://{host}:{port}", file=__import__("sys").stderr)
    except OSError:
        pass  # 端口被占,说明已有实例起了 Web 台,静默跳过


if __name__ == "__main__":
    main()
