"""lm-mem Web 记忆。

基于标准库 http.server,零额外依赖。仅本机访问,用于在浏览器里
查看/检索已保存的记忆,并支持按 id 删除单条(需二次确认)。

启动:
    uv run python -m web.py or LM_MEM_WEB_PORT=8080 uv run python web.py
    # 默认 http://127.0.0.1:7531

路由:
    /                  列表(支持 ?user_id=&agent_id=&app_id=&run_id=&q=&p=)
    /search?q=...      语义检索
    /mem/<id>          单条详情
    /api/...           上述各页面的 JSON 版本
    POST /mem/<id>/delete        删除单条(浏览器表单,303 跳回 /)
    POST /api/mem/<id>/delete    删除单条(JSON 返回)
    DELETE /api/mem/<id>         删除单条(JSON 返回)
"""

from __future__ import annotations

import html
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import backend as _db

# 为避免与 helpers 命名冲突(都有 _SCOPE_KEYS 等),建短别名。
import memory_utils as _hlp

_VERSION = "0.3.0"
def _delete_fn(mem_id):
    """删除单条记忆(直接调 Chroma,不依赖 MCP 工具层)。"""
    if not _db._collection.get(ids=[mem_id])["ids"]:
        return json.dumps({"ok": False, "message": f"未找到 id={mem_id} 的记忆。"})
    _db._collection.delete(ids=[mem_id])
    return json.dumps({"ok": True, "id": mem_id, "message": f"已删除 id={mem_id}"})

_HOST = "127.0.0.1"
_PORT = 7531

_PAGE_CSS = """
:root{
  --bg:#fafafa;--surface:#fff;--border:#ebecf0;--text:#1a1a2e;--muted:#8b8fa3;
  --accent:#6366f1;--accent-hover:#4f46e5;--accent-soft:#f0f0ff;
  --green:#059669;--amber:#d97706;--red:#ef4444;
  --radius:12px;--radius-sm:8px;--shadow:0 1px 3px rgba(0,0,0,.04),0 1px 2px rgba(0,0,0,.03);
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#09090b;--surface:#121217;--border:#1f1f2a;--text:#e4e4ed;--muted:#727282;
    --accent:#818cf8;--accent-hover:#a5b4fc;--accent-soft:#1c1c2a;
    --shadow:0 1px 2px rgba(0,0,0,.22);
  }
}
*{box-sizing:border-box}
body{font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     margin:0;color:var(--text);background:var(--bg);-webkit-font-smoothing:antialiased}
.wrap{max-width:1600px;margin:0 auto;padding:0 24px 80px}
header.topbar{position:sticky;top:0;z-index:50;background:rgba(250,250,250,.82);
     border-bottom:1px solid var(--border);backdrop-filter:saturate(180%) blur(12px);
     -webkit-backdrop-filter:saturate(180%) blur(12px)}
@media(prefers-color-scheme:dark){header.topbar{background:rgba(9,9,11,.82)}}
.topbar-inner{max-width:1600px;margin:0 auto;padding:14px 24px;display:flex;
     align-items:center}
.topbar h1{font-size:16px;margin:0;font-weight:640;letter-spacing:-.01em}
.topbar h1 .ver{font-size:11px;color:var(--muted);font-weight:400;margin-left:8px}
form.filters{display:flex;flex-wrap:wrap;gap:8px;margin:24px 0 16px;align-items:end}
form.filters .field{display:flex;flex-direction:column;gap:4px}
form.filters .field label{font-size:11px;color:var(--muted);padding-left:2px}
input,button,select{font:inherit;padding:8px 12px;border:1px solid var(--border);
     border-radius:var(--radius-sm);background:var(--surface);color:var(--text);
     transition:border .18s,box-shadow .18s,background .18s}
input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
input[type=text]{min-width:160px}
input[type=text].grow{flex:1;min-width:220px}
button{background:var(--accent);color:#fff;border-color:var(--accent);
       cursor:pointer;font-weight:500;padding:8px 18px;border-radius:var(--radius-sm)}
button:hover{background:var(--accent-hover);border-color:var(--accent-hover)}
button.ghost{background:transparent;color:var(--text);border-color:var(--border)}
button.ghost:hover{background:var(--accent-soft);color:var(--accent);border-color:transparent}
button.ghost.icon{padding:6px 12px;font-size:13px}
.toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;
         margin-bottom:16px;flex-wrap:wrap}
.toolbar .count{color:var(--muted);font-size:13px}
.pager{display:flex;gap:4px;align-items:center;flex-wrap:wrap}
.pager a,.pager span{padding:6px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);
       text-decoration:none;color:var(--text);font-size:13px;background:var(--surface);
       transition:all .15s}
.pager a:hover{background:var(--accent-soft);color:var(--accent);border-color:transparent}
.pager .cur{background:var(--accent);color:#fff;border-color:var(--accent)}
.pager .gap{border:none;background:transparent;color:var(--muted)}
.table-wrap{overflow-x:auto;border-radius:var(--radius);overflow:hidden;
    background:var(--surface);box-shadow:var(--shadow);border:1px solid var(--border)}
.mem-table{border-collapse:collapse;width:100%;min-width:640px}
.mem-table td,.mem-table th{padding:5px 12px;text-align:left;font-size:12px;
    vertical-align:middle;border-bottom:1px solid var(--border)}
.mem-table tr:last-child td{border-bottom:0}
.mem-table th{background:var(--bg);color:var(--muted);font-weight:600;font-size:11px;
    text-transform:uppercase;letter-spacing:.05em;position:sticky;top:0;z-index:1;padding:6px 12px}
.mem-table tbody tr{transition:background .12s}
.mem-table tbody tr:hover td{background:var(--accent-soft)}
.mem-table td.time{color:var(--muted);font-family:"SF Mono",ui-monospace,monospace;
    white-space:nowrap;font-size:11px;width:85px}
.mem-table td.entities{width:200px}
.mem-table td.entities .scope{display:inline-block;font-family:"SF Mono",ui-monospace,monospace;
    font-size:11px;color:var(--muted);background:var(--bg);border:1px solid var(--border);
    padding:2px 9px;border-radius:20px;margin:1px 4px 2px 0}
.mem-table td.content{max-width:600px}
.mem-table td.content a{color:var(--text);text-decoration:none;display:block;
    display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
    font-size:12px;line-height:1.35;height:calc(1.35em*2);text-overflow:ellipsis}
.mem-table td.content a:hover{color:var(--accent)}
.mem-table td.categories{width:180px}
.mem-table td.categories .tag{display:inline-block;background:var(--accent-soft);
    color:var(--accent);padding:2px 9px;border-radius:20px;font-size:11px;margin:1px 3px 1px 0}
.mem-table td.categories .tag.cat{background:rgba(217,119,6,.1);color:var(--amber)}
@media(max-width:640px){.mem-table td.content{max-width:55vw}}
.empty{text-align:center;padding:64px 20px;color:var(--muted)}
.empty .big{font-size:44px;margin-bottom:12px;opacity:.45}
.muted{color:var(--muted)}
h2{font-size:15px;margin:28px 0 12px;font-weight:600}
pre{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
    padding:16px;white-space:pre-wrap;word-break:break-word;overflow:auto;
    font-size:12.5px;font-family:"SF Mono",ui-monospace,monospace}
.kv{display:grid;grid-template-columns:auto 1fr;gap:8px 18px;font-size:13px;margin:4px 0}
.kv dt{color:var(--muted);font-weight:500}
.kv dd{margin:0;word-break:break-word}
.error-box{background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.25);color:var(--red);
    padding:14px 16px;border-radius:var(--radius)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
      padding:14px 16px;margin-bottom:10px;box-shadow:var(--shadow);transition:border .15s}
.card:hover{border-color:var(--accent)}
.card .top{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.card .id{color:var(--muted);font-size:12px;font-family:"SF Mono",ui-monospace,monospace}
.card .id a{color:inherit;text-decoration:none}
.card .id a:hover{color:var(--accent)}
.card .sim{color:var(--green);font-size:12px;font-weight:600;
     background:rgba(5,150,105,.1);padding:1px 8px;border-radius:20px}
.card .content{margin:4px 0;white-space:pre-wrap;word-break:break-word;color:var(--text)}
.card a.content{display:block;text-decoration:none;color:var(--text);border-radius:6px;
     margin:4px -4px;padding:4px;transition:background .12s}
.card a.content:hover{background:var(--accent-soft)}
.card .content.clamp{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;
     overflow:hidden;cursor:pointer}
.card .meta{color:var(--muted);font-size:12px;margin-top:8px;display:flex;
     flex-wrap:wrap;gap:4px 10px}
.card .meta .tag{background:var(--accent-soft);color:var(--accent);padding:1px 8px;
     border-radius:20px;font-size:11px}
.card .meta .scope{font-family:"SF Mono",ui-monospace,monospace;font-size:11px}
.card .meta .expire{color:var(--amber)}
.card .actions{margin-top:10px;display:flex;gap:8px}
.card .del-inline{background:transparent;border:1px solid var(--border);color:var(--muted);
    padding:3px 10px;font-size:12px;border-radius:6px;cursor:pointer}
.card .del-inline:hover{background:rgba(239,68,68,.06);color:var(--red);border-color:var(--red)}
.danger{background:var(--red);color:#fff;border-color:var(--red);font-weight:500;
    border-radius:var(--radius-sm)}
.danger:hover{background:#dc2626;border-color:#dc2626}
.confirm-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;
    background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.25);border-radius:var(--radius);
    padding:12px 16px;margin-bottom:16px}
.confirm-bar .msg{color:var(--red);font-size:13px;font-weight:500}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.3);opacity:0;visibility:hidden;
    transition:opacity .22s;z-index:60;backdrop-filter:blur(2px)}
.overlay.show{opacity:1;visibility:visible}
.drawer{position:fixed;top:0;right:0;bottom:0;width:500px;max-width:100vw;
    background:var(--bg);border-left:1px solid var(--border);
    box-shadow:-4px 0 40px rgba(0,0,0,.08);transform:translateX(104%);
    transition:transform .28s cubic-bezier(.32,.72,0,1);z-index:70;
    display:flex;flex-direction:column}
.drawer.show{transform:translateX(0)}
.drawer header{display:flex;align-items:center;gap:10px;padding:16px 20px;
    background:var(--surface);border-bottom:1px solid var(--border)}
.drawer header .title{font-weight:640;font-size:15px;flex:1;color:var(--text)}
.drawer header .close{background:transparent;border:none;color:var(--muted);
    font-size:22px;cursor:pointer;padding:2px 6px;line-height:1;border-radius:8px;
    transition:all .15s}
.drawer header .close:hover{background:var(--accent-soft);color:var(--accent)}
.drawer .body{flex:1;overflow-y:auto;padding:18px 20px}
.drawer .d-content{background:var(--surface);border:1px solid var(--border);
    border-radius:var(--radius-sm);padding:14px 16px;white-space:pre-wrap;
    word-break:break-word;margin-bottom:16px;font-size:13px;line-height:1.6}
.drawer .d-id{font-family:"SF Mono",ui-monospace,monospace;font-size:12px;color:var(--muted);
    background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);
    padding:8px 12px;word-break:break-all;margin-bottom:16px}
.drawer .d-section{font-size:11px;color:var(--muted);text-transform:uppercase;
    letter-spacing:.06em;margin:18px 0 8px;font-weight:600}
.drawer .d-meta{display:flex;flex-wrap:wrap;gap:6px 8px;font-size:13px}
.drawer .d-meta .tag{background:var(--accent-soft);color:var(--accent);
    padding:3px 10px;border-radius:20px;font-size:11px}
.drawer .d-meta .scope{font-family:"SF Mono",ui-monospace,monospace;font-size:11px;
    color:var(--muted);background:var(--surface);border:1px solid var(--border);
    padding:3px 10px;border-radius:20px}
.drawer .d-kv{font-size:13px;color:var(--text)}
.drawer .d-kv div{padding:6px 0;border-bottom:1px solid var(--border);display:flex;gap:10px}
.drawer .d-kv div:last-child{border-bottom:0}
.drawer .d-kv .k{color:var(--muted);min-width:65px;font-weight:500}
.drawer .d-loading{text-align:center;padding:40px 0;color:var(--muted)}
.drawer .d-error{color:var(--red);text-align:center;padding:40px 0}
.drawer footer{padding:16px 20px;border-top:1px solid var(--border);background:var(--surface)}
.tools-right{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.filters.collapsed{display:none}
.filter-active{display:inline-block;width:7px;height:7px;border-radius:50%;
    background:var(--accent);margin-left:3px}
@media(max-width:640px){
  .drawer{width:100vw}
  .mem-table td.content{max-width:55vw}
  form.filters .field{flex:1 1 45%}
  input[type=text]{min-width:0;width:100%}
  .topbar-inner{padding:12px 16px}
}
"""


def _fmt_ts(ts):
    if not ts:
        return "-"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except Exception:
        return str(ts)


def _fmt_ts_short(ts):
    if not ts:
        return "—"
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(ts))
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


def _esc(s):
    return html.escape(str(s) if s is not None else "")


def _del_form(mem_id, inline=False, confirm_msg=None):
    """删除单条的 POST 表单。浏览器提交,服务端 303 跳回 /。"""
    msg = confirm_msg or f"确认删除记忆 {mem_id[:8]}…?此操作不可撤销。"
    btn_cls = "del-inline" if inline else "danger"
    btn_txt = "🗑 删除" if inline else "🗑 删除这条记忆"
    return (
        f'<form method="post" action="/mem/{_esc(mem_id)}/delete" '
        f'class="{"actions" if not inline else ""}" '
        f'onsubmit="return confirm(\'{_esc(msg)}\')">'
        f'<button type="submit" class="{btn_cls}">{btn_txt}</button>'
        f"</form>"
    )


_PAGE_SIZE = 30


def _scope_inputs(scope_vals):
    """带 label 的作用域输入,横向排列。"""
    return "".join(
        f'<div class="field"><label>{k}</label>'
        f'<input type="text" name="{k}" value="{_esc(scope_vals.get(k, ""))}" placeholder="—"></div>'
        for k in _hlp._SCOPE_KEYS
    )


def _pager(base_url, page, total_pages):
    if total_pages <= 1:
        return ""
    parts = []
    prev_cls = "" if page > 1 else ' style="visibility:hidden"'
    parts.append(f'<a{prev_cls} href="{base_url}&p={page-1}">‹ 上一页</a>')
    # 简洁页码:首页 + 当前附近 + 末页
    shown = {1, total_pages, page, page - 1, page + 1}
    last = 0
    for p in sorted(shown):
        if p < 1 or p > total_pages:
            continue
        if p - last > 1:
            parts.append('<span class="gap">…</span>')
        if p == page:
            parts.append(f'<span class="cur">{p}</span>')
        else:
            parts.append(f'<a href="{base_url}&p={p}">{p}</a>')
        last = p
    next_cls = "" if page < total_pages else ' style="visibility:hidden"'
    parts.append(f'<a{next_cls} href="{base_url}&p={page+1}">下一页 ›</a>')
    return f'<div class="pager">{"".join(parts)}</div>'


def _render_list(records, scope_vals, q="", page=1, notice=None):
    total = len(records)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * _PAGE_SIZE
    page_records = records[start:start + _PAGE_SIZE]

    q_field = (
        '<div class="field" style="flex:2;min-width:240px">'
        f'<label>关键词 / 语义检索</label>'
        f'<input type="text" class="grow" name="q" value="{_esc(q)}" placeholder="留空则按作用域列出"></div>'
    )
    rows = []
    for r in page_records:
        # 时间
        time_html = f'<td class="time">{_esc(_fmt_ts_short(r["created_at"]))}</td>'
        # 作用域(scope)
        ent = "".join(
            f'<span class="scope">{_esc(k)}={_esc(v)}</span>'
            for k, v in r["scope"].items()
        ) or '<span class="muted">—</span>'
        ent_html = f'<td class="entities">{ent}</td>'
        # 内容(点击进抽屉)
        content_html = (
            f'<td class="content"><a class="mem-link" href="/mem/{_esc(r["id"])}">'
            f'{_esc(r["content"])}</a></td>'
        )
        # 分类(tags + metadata.category)
        cat = (r.get("metadata") or {}).get("category")
        if cat:
            cat_inner = f'<span class="tag cat">{_esc(cat)}</span>'
        else:
            cat_inner = '<span class="muted">—</span>'
        cat_html = f'<td class="categories">{cat_inner}</td>'
        rows.append(f'<tr data-mid="{_esc(r["id"])}">{time_html}{ent_html}{content_html}{cat_html}</tr>')

    if not rows:
        body = '<div class="empty"><div class="big">📭</div>没有匹配的记忆。</div>'
    else:
        body = (
            '<div class="table-wrap"><table class="mem-table">'
            '<thead><tr><th>时间</th><th>作用域</th><th>内容</th><th>分类</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>'
        )

    base = "?" + "&".join(
        f"{k}={_esc(scope_vals.get(k, '') or '')}" for k in _hlp._SCOPE_KEYS
    ) + f"&q={_esc(q)}"
    pager = _pager(base, page, total_pages)

    notice_html = ""
    if notice:
        notice_html = (
            f'<div class="confirm-bar"><span class="msg">{_esc(notice)}</span>'
            f'<a href="/" style="font-size:13px;color:var(--muted);text-decoration:none">×</a></div>'
        )

    has_filter = bool(q) or any(v for v in scope_vals.values())
    filter_dot = '<span class="filter-active" title="当前有筛选条件"></span>' if has_filter else ""
    filter_form_cls = "filters" + ("" if has_filter else " collapsed")

    return _page("记忆", f"""
        {notice_html}
        <div class="toolbar">
          <span class="count">共 {total} 条{f" · 第 {page}/{total_pages} 页" if total_pages>1 else ""}</span>
          <div class="tools-right">
            <button class="ghost icon" id="filter-toggle">筛选 <span id="filter-arrow">▾</span>{filter_dot}</button>
            <button class="ghost icon" onclick="location.reload()" title="重新加载">🔄 刷新</button>
            {pager if total_pages > 1 else ""}
          </div>
        </div>
        <form class="{filter_form_cls}" id="filters" method="get" action="/">
          {_scope_inputs(scope_vals)}
          {q_field}
          <button type="submit">筛选</button>
        </form>
        {body}
        {f'<div class="toolbar" style="justify-content:flex-end">{pager}</div>' if total_pages>1 else ""}
        <script>
        (function(){{
          var f=document.getElementById('filters'),b=document.getElementById('filter-toggle'),
              a=document.getElementById('filter-arrow');
          if(!f||!b||!a)return;
          b.addEventListener('click',function(){{
            var c=f.classList.toggle('collapsed');
            a.textContent=c?'▾':'▴';
          }});
        }})();
        </script>
    """)


def _render_detail(rec):
    if not rec:
        return _page("未找到", '<div class="empty"><div class="big">🔍</div>没有这条记忆。</div>')
    pre = html.escape(json.dumps(rec, ensure_ascii=False, indent=2))
    scope = " ".join(f"{k}={v}" for k, v in rec["scope"].items()) or "—"
    tags = "".join(
        f'<span class="tag">{_esc(t.strip())}</span>'
        for t in str(rec["tags"]).split(",") if t.strip()
    ) or '<span class="muted">—</span>'
    return _page(f"记忆 {rec['id'][:8]}", f"""
        <div class="card">
          <div class="top"><span class="id">{_esc(rec["id"])}</span></div>
          <div class="content">{_esc(rec["content"])}</div>
          <div class="meta">
            <span class="scope">{_esc(scope)}</span>
          </div>
        </div>
        <h2>属性</h2>
        <div class="card">
          <dl class="kv">
            <dt>标签</dt><dd>{tags}</dd>
            <dt>创建时间</dt><dd>{_esc(_fmt_ts(rec["created_at"]))}</dd>
            <dt>更新时间</dt><dd>{_esc(_fmt_ts(rec["updated_at"]))}</dd>
            <dt>过期时间</dt><dd>{_esc(_fmt_ts(rec["expires_at"]))}</dd>
          </dl>
        </div>
        {_del_form(rec["id"])}
        <h2>原始数据</h2>
        <pre>{pre}</pre>
    """)


def _render_search(records, q):
    if not records:
        body = '<div class="empty"><div class="big">🔍</div>没有匹配的记忆。</div>'
    else:
        rows = "".join(
            f'<tr><td><span class="sim" style="display:inline-block">{r["similarity"]:.2f}</span></td>'
            f'<td><a href="/mem/{_esc(r["id"])}">{_esc(r["content"][:80])}</a></td>'
            f'<td><span class="scope">{_esc(" ".join(f"{k}={v}" for k,v in r["scope"].items()) or "—")}</span></td></tr>'
            for r in records
        )
        body = f'<table><thead><tr><th>相似度</th><th>内容</th><th>作用域</th></tr></thead><tbody>{rows}</tbody></table>'
    return _page(f"搜索: {q}", f"""
        <form class="filters" method="get" action="/search">
          <div class="field" style="flex:1;min-width:260px">
            <label>语义检索</label>
            <input type="text" class="grow" name="q" value="{_esc(q)}" placeholder="输入关键词">
          </div>
          <button type="submit">搜索</button>
        </form>
        {body}
    """)


_DRAWER_JS = r"""
(function(){
  var ov=document.getElementById('ov'),dr=document.getElementById('dr'),
      bt=document.getElementById('dr-body'),ti=document.getElementById('dr-title'),
      ft=document.getElementById('dr-foot'),cl=document.getElementById('dr-close');
  if(!dr) return;
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
    return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function ts(v){if(!v)return '—';var d=new Date(v*1000);
    if(isNaN(d))return String(v);
    var p=function(n){return n<10?'0'+n:n;};
    return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+
      ' '+p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());}
  function close(){ov.classList.remove('show');dr.classList.remove('show');
    dr.setAttribute('aria-hidden','true');bt.innerHTML='';ft.hidden=true;ft.innerHTML='';}
  function open(mid){
    ti.textContent='记忆详情';
    bt.innerHTML='<div class="d-loading">加载中…</div>';
    ft.hidden=true;
    ov.classList.add('show');dr.classList.add('show');
    dr.setAttribute('aria-hidden','false');
    fetch('/api/mem/'+encodeURIComponent(mid)).then(function(r){return r.json();})
      .then(function(r){render(r,mid);})
      .catch(function(){bt.innerHTML='<div class="d-error">加载失败</div>';});
  }
  function render(r,mid){
    if(!r||!r.id){bt.innerHTML='<div class="d-error">未找到该记忆</div>';ft.hidden=true;return;}
    ti.textContent='记忆详情';
    var md=r.metadata||{}; var mdKeys=Object.keys(md);
    var mdJson=JSON.stringify(md,null,2);
    var scopeJson=JSON.stringify(r.scope||{},null,2);
    var scopeKeys=Object.keys(r.scope||{});
    bt.innerHTML=
      '<div class="d-section">ID</div>'
      +'<div class="d-id">'+esc(r.id)+'</div>'
      +'<div class="d-section">内容</div>'
      +'<div class="d-content">'+esc(r.content)+'</div>'
      +'<div class="d-kv">'
        +'<div><span class="k">创建时间</span><span>'+esc(ts(r.created_at))+'</span></div>'
        +'<div><span class="k">更新时间</span><span>'+esc(ts(r.updated_at))+'</span></div>'
        +(r.expires_at?'<div><span class="k">过期时间</span><span>'+esc(ts(r.expires_at))+'</span></div>':'')
      +'</div>'
      +'<div class="d-section">作用域</div>'
      +(scopeKeys.length?'<div class="d-content">'+esc(scopeJson)+'</div>':'<span class="muted">—</span>')
      +(mdKeys.length?('<div class="d-section">元数据</div><div class="d-content">'+esc(mdJson)+'</div>'):'<div class="d-section">元数据</div><span class="muted">—</span>')
    // 底部删除按钮
    ft.hidden=false;
    ft.innerHTML='<form method="post" action="/mem/'+esc(mid)+'/delete" '
      +'onsubmit="return confirm(\'确认删除?不可撤销。\')">'
      +'<button type="submit" class="danger" style="width:100%">🗑 删除这条记忆</button>'
      +'</form>';
  }
  // 点表格行 → 开抽屉;ctrl/shift/中键放行(新标签打开链接)
  document.addEventListener('click',function(e){
    if(e.metaKey||e.ctrlKey||e.shiftKey||e.button!==0)return;
    var a=e.target.closest('a.mem-link');
    var tr=e.target.closest('tr[data-mid]');
    if(a){e.preventDefault();open(a.getAttribute('href').slice(5));return;}
    if(tr){e.preventDefault();open(tr.getAttribute('data-mid'));return;}
  });
  ov.addEventListener('click',close);
  cl.addEventListener('click',close);
  document.addEventListener('keydown',function(e){if(e.key==='Escape')close();});
  // 从详情页返回时若带 ?deleted=,列表已自行处理;抽屉不主动开
})();
"""


def _page(title, body):
    return (
        "<!doctype html><html lang='zh-CN'><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(title)} · lm-mem</title>"
        f"<style>{_PAGE_CSS}</style></head>"
        f"<body><header class='topbar'><div class='topbar-inner'>"
        f"<h1>🧠 lm-mem<span class='ver'>v{_VERSION}</span></h1>"
        f"</div></header><div class='wrap'>{body}</div>"
        "<div class='overlay' id='ov'></div>"
        "<aside class='drawer' id='dr' aria-hidden='true'>"
        "<header><span class='title' id='dr-title'>—</span>"
        "<button class='close' id='dr-close' aria-label='关闭'>×</button></header>"
        "<div class='body' id='dr-body'></div>"
        "<footer id='dr-foot' hidden></footer>"
        "</aside>"
        "<script>"
        + _DRAWER_JS
        + "</script>"
        "</body></html>"
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

    def _local_origin_ok(self):
        """同源校验:仅允许本机 origin 的写请求,挡掉跨站 CSRF。

        浏览器表单会带 Referer;fetch 带 Origin。两者都空时(如 curl)
        放行——工具本就是本机脚本可用。
        """
        origin = (self.headers.get("Origin") or "").strip()
        referer = (self.headers.get("Referer") or "").strip()
        host = self.headers.get("Host", "")
        for val in (origin, referer):
            if not val:
                continue
            # 形如 http://127.0.0.1:7531/... ,Host 必须出现在值里
            if host and host not in val:
                return False
        return True

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path.startswith("/api/mem/") and path.endswith("/delete"):
            mid = path[len("/api/mem/"):-len("/delete")]
        elif path.startswith("/api/mem/"):
            mid = path[len("/api/mem/"):]
        else:
            return self._send(404, json.dumps({"error": "not found"}),
                              "application/json; charset=utf-8")
        if not self._local_origin_ok():
            return self._send(403, json.dumps({"error": "forbidden origin"}),
                              "application/json; charset=utf-8")
        result = json.loads(_delete_fn(mid))
        code = 200 if result["ok"] else 404
        return self._send(code, json.dumps(result, ensure_ascii=False),
                          "application/json; charset=utf-8")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        # 单条删除:/mem/<id>/delete  或  /api/mem/<id>/delete
        mid = None
        api = False
        if path.startswith("/mem/") and path.endswith("/delete"):
            mid = path[len("/mem/"):-len("/delete")]
        elif path.startswith("/api/mem/") and path.endswith("/delete"):
            mid = path[len("/api/mem/"):-len("/delete")]
            api = True
        if mid is None:
            return self._send(404, json.dumps({"error": "not found"}),
                              "application/json; charset=utf-8")
        if not self._local_origin_ok():
            return self._send(403, json.dumps({"error": "forbidden origin"}),
                              "application/json; charset=utf-8")
        result = json.loads(_delete_fn(mid))
        ok = result["ok"]
        if api:
            return self._send(200 if ok else 404,
                              json.dumps(result, ensure_ascii=False),
                              "application/json; charset=utf-8")
        # 浏览器表单:跳回列表,带结果提示
        return self._redirect(f"/?deleted={1 if ok else 0}&id={_esc(mid[:8])}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/version" or path == "/api/version":
            return self._send(200, json.dumps({"version": _VERSION}, ensure_ascii=False),
                              "application/json; charset=utf-8")

        try:
            if path == "/api/list" or path == "/":
                sv = self._scope_from_qs(qs)
                q = qs.get("q", [""])[0].strip()
                records = (_search_records(q, **sv) if q
                           else _list_records(**sv))
                if path == "/api/list":
                    return self._send(200, json.dumps({"ok": True, "count": len(records),
                                      "items": records, "message": f"返回 {len(records)} 条"},
                                      ensure_ascii=False),
                                      "application/json; charset=utf-8")
                page = int(qs.get("p", ["1"])[0] or "1")
                notice = None
                if qs.get("deleted", [""])[0] == "1":
                    short = qs.get("id", [""])[0]
                    notice = f"✓ 已删除记忆 {short}…" if short else "✓ 已删除"
                elif qs.get("deleted", [""])[0] == "0":
                    notice = "✗ 删除失败:未找到该记忆"
                return self._send(200, _render_list(records, sv, q, page=page, notice=notice))

            if path == "/api/search":
                q = qs.get("q", [""])[0].strip()
                sv = self._scope_from_qs(qs)
                items = _search_records(q, **sv)
                return self._send(
                    200, json.dumps({"ok": True, "count": len(items),
                                     "items": items, "message": f"搜索到 {len(items)} 条"},
                                    ensure_ascii=False),
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

            return self._send(404, _page("404", '<div class="empty"><div class="big">🚫</div>没有这个页面。</div>'))
        except Exception as exc:  # noqa: BLE001
            return self._send(500, _page("出错", f'<div class="error-box"><pre>{_esc(exc)}</pre></div>'))


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
    print(f"lm-mem: http://{host}:{port}  (只读, Ctrl+C 退出)")
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
        import sys as _sys
        _sys.stderr.write(f"[lm-mem] Web 记忆: http://{host}:{port} (只读)\n")
        _sys.stderr.flush()
    except OSError:
        pass  # 端口被占,说明已有实例起了 Web 台,静默跳过


if __name__ == "__main__":
    main()
