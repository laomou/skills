"""lm-mem server 的单元/集成测试。

用临时目录作为 ChromaDB 落盘路径,避免污染真实记忆库。
运行:  uv run pytest -q
"""

import importlib
import json
import os
import socket
import sys
import tempfile
import pytest

# 共享后端相关环境变量:每个 srv 测试前清空,避免用例间互相污染。
_BACKEND_ENV = (
    "MEMORY_CHROMA_HOST",
    "MEMORY_CHROMA_PORT",
    "MEMORY_CHROMA_URL",
)


@pytest.fixture()
def srv():
    """每个测试用独立的临时 DB,从 mcp_tools + db + helpers 组合命名空间。"""
    tmp = tempfile.mkdtemp(prefix="lm-mem-test-")
    os.environ["MEMORY_DB_PATH"] = tmp
    for key in _BACKEND_ENV:
        os.environ.pop(key, None)
    for mod_name in ("mcp_tools", "db", "helpers"):
        sys.modules.pop(mod_name, None)

    import db as _db
    import helpers as _hlp

    _db = importlib.reload(_db)
    _hlp = importlib.reload(_hlp)
    # mcp_tools 最后 reload,让它重新 import 新的 _db / _hlp
    import mcp_tools as _mt
    _mt = importlib.reload(_mt)

    srv = type("_Srv", (), {})()
    srv.__dict__.update({k: v for k, v in _mt.__dict__.items() if not k.startswith("_")})
    srv.__dict__.update({
        "_collection": _db._collection,
        "_client": _db._client,
        "_connect": _db._connect,
        "_init_client": _db._init_client,
        "_is_expired": _hlp._is_expired,
    })
    yield srv


def _free_port():
    """取一个当前空闲的本地端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _r(msg):
    """所有 MCP 工具都返回 JSON 字符串,统一解析。"""
    return json.loads(msg)


def _id(msg):
    """成功保存后取 id;查重命中时用 duplicate_id 请另调 _r。"""
    return _r(msg)["id"]


def _contents(items):
    return [it["content"] for it in items]


def test_add_and_get(srv):
    out = _r(srv.add_memory(content="用户喜欢简洁的回答", user_id="u1"))
    assert out["ok"] is True
    mem_id = out["id"]
    got = _r(srv.get_memory(mem_id))
    assert got["ok"] is True
    assert got["item"]["content"] == "用户喜欢简洁的回答"
    assert got["item"]["scope"]["user_id"] == "u1"


def test_semantic_search_finds_paraphrase(srv):
    # #1 语义检索:用词不同也应命中。
    srv.add_memory(content="用户偏好简短的答复", user_id="u1")
    res = _r(srv.search_memories(query="这个人喜不喜欢啰嗦的长篇大论", user_id="u1"))
    assert res["ok"] is True
    assert any("简短" in c for c in _contents(res["items"]))


def test_dedup_blocks_similar(srv):
    # #2 去重:高度相似不插入。
    srv.add_memory(content="我最喜欢的语言是 Python", user_id="u1")
    dup = _r(srv.add_memory(content="我最喜欢的语言是 Python", user_id="u1"))
    assert dup["ok"] is False
    assert dup["reason"] == "duplicate"
    assert "duplicate_id" in dup
    assert dup["similarity"] >= 0.85
    # force 可强制新增
    forced = _r(srv.add_memory(content="我最喜欢的语言是 Python", user_id="u1", force=True))
    assert forced["ok"] is True
    assert "id" in forced


def test_dedup_scoped_per_user(srv):
    # 不同作用域不应互相触发去重。
    srv.add_memory(content="喜欢深色主题", user_id="u1")
    other = _r(srv.add_memory(content="喜欢深色主题", user_id="u2"))
    assert other["ok"] is True


def test_metadata_store_and_filter(srv):
    # #3 自定义 metadata + 过滤。
    srv.add_memory(
        content="部署用 Kubernetes",
        user_id="u1",
        metadata=json.dumps({"category": "infra", "importance": "high"}),
    )
    srv.add_memory(content="午饭吃了面", user_id="u1",
                   metadata=json.dumps({"category": "misc"}))
    res = _r(srv.search_memories(
        query="部署方案", user_id="u1",
        metadata_filter=json.dumps({"category": "infra"}),
    ))
    contents = _contents(res["items"])
    assert any("Kubernetes" in c for c in contents)
    assert not any("面" in c for c in contents)
    listed = _r(srv.get_memories(user_id="u1",
                                 metadata_filter=json.dumps({"category": "misc"})))
    contents = _contents(listed["items"])
    assert any("面" in c for c in contents)
    assert not any("Kubernetes" in c for c in contents)


def test_bad_metadata_rejected(srv):
    with pytest.raises(ValueError):
        srv.add_memory(content="x", metadata="not-json")
    with pytest.raises(ValueError):
        srv.add_memory(content="x", metadata="[1,2,3]")  # 非对象


def test_messages_input(srv):
    # #4 messages 数组输入。
    msgs = json.dumps([
        {"role": "user", "content": "我住在上海"},
        {"role": "assistant", "content": "记住了"},
    ])
    out = _r(srv.add_memory(messages=msgs, user_id="u1"))
    assert out["ok"] is True
    res = _r(srv.search_memories(query="用户在哪个城市", user_id="u1"))
    assert any("上海" in c for c in _contents(res["items"]))


def test_empty_input_rejected(srv):
    out = _r(srv.add_memory())
    assert out["ok"] is False
    assert "content" in out["message"] or "messages" in out["message"]


def test_update_content_and_metadata(srv):
    add = _r(srv.add_memory(content="旧内容", user_id="u1",
                            metadata=json.dumps({"category": "a"})))
    mid = add["id"]
    upd = _r(srv.update_memory(mid, content="新内容", metadata=json.dumps({"importance": "low"})))
    assert upd["ok"] is True
    got = _r(srv.get_memory(mid))
    item = got["item"]
    assert item["content"] == "新内容"
    assert item["metadata"]["importance"] == "low"
    assert item["metadata"]["category"] == "a"  # 原有 metadata 保留


def test_stats(srv):
    # #6 统计。
    srv.add_memory(content="a", user_id="u1", tags="pref",
                   metadata=json.dumps({"category": "x"}))
    srv.add_memory(content="b", user_id="u1", tags="pref", force=True,
                   metadata=json.dumps({"category": "y"}))
    stats = _r(srv.memory_stats(user_id="u1"))
    assert stats["ok"] is True
    assert stats["active"] == 2
    assert stats["total"] == 2
    assert stats["expired"] == 0
    assert stats["tags"]["pref"] == 2
    assert stats["categories"]["x"] == 1
    assert stats["categories"]["y"] == 1


def test_stats_excludes_expired_from_aggregates(srv):
    # #1 修复:过期项不计入有效数/标签/分类聚合,只体现在"已过期"。
    srv.add_memory(content="有效", user_id="u1", tags="live")
    add = _r(srv.add_memory(content="过期", user_id="u1", tags="dead",
                            force=True, ttl_seconds=3600))
    mid = add["id"]
    g = srv._collection.get(ids=[mid], include=["metadatas"])
    meta = g["metadatas"][0]
    meta["expires_at"] = 1.0
    srv._collection.update(ids=[mid], metadatas=[meta])
    stats = _r(srv.memory_stats(user_id="u1"))
    assert stats["active"] == 1
    assert stats["expired"] == 1
    assert stats["total"] == 2
    assert stats["tags"].get("live") == 1
    assert "dead" not in stats["tags"]  # 过期标签不计入聚合


def test_update_ttl_renew_and_clear(srv):
    # #2 增强:update_memory 可续期与清除过期。
    mid = _id(srv.add_memory(content="临时", user_id="u1", ttl_seconds=3600))
    # 清除过期 -> 变永久(哨兵值 0,检索不再视为过期)
    srv.update_memory(mid, ttl_seconds=-1)
    meta = srv._collection.get(ids=[mid], include=["metadatas"])["metadatas"][0]
    assert not meta.get("expires_at")  # 0 / 不存在都算永久
    assert not srv._is_expired(meta)
    # 重新续期
    srv.update_memory(mid, ttl_seconds=7200)
    meta = srv._collection.get(ids=[mid], include=["metadatas"])["metadatas"][0]
    assert meta["expires_at"] > 0
    # ttl_seconds=0 不动过期设置,但仍能改文本
    srv.update_memory(mid, content="改了文本")
    meta = srv._collection.get(ids=[mid], include=["metadatas"])["metadatas"][0]
    assert meta["expires_at"] > 0


def test_search_overfetch_past_expired(srv):
    # #3:即使前面挤了很多过期项,有效项仍能被返回。
    for i in range(30):
        mid = _id(srv.add_memory(content=f"过期便签 {i}", user_id="u1",
                                 force=True, ttl_seconds=3600))
        g = srv._collection.get(ids=[mid], include=["metadatas"])
        m = g["metadatas"][0]
        m["expires_at"] = 1.0
        srv._collection.update(ids=[mid], metadatas=[m])
    srv.add_memory(content="这是唯一有效的便签", user_id="u1", force=True)
    res = _r(srv.search_memories(query="便签", user_id="u1", limit=5))
    contents = _contents(res["items"])
    assert any("这是唯一有效的便签" in c for c in contents)
    assert not any("过期便签" in c for c in contents)


def test_export_json_and_csv(srv):
    srv.add_memory(content="导出测试", user_id="u1",
                   metadata=json.dumps({"category": "z"}))
    js = _r(srv.export_memories(fmt="json", user_id="u1"))
    assert js["ok"] is True
    assert js["fmt"] == "json"
    assert js["count"] == 1
    assert js["data"][0]["content"] == "导出测试"
    assert js["data"][0]["metadata"]["category"] == "z"

    csv_ret = _r(srv.export_memories(fmt="csv", user_id="u1"))
    assert csv_ret["fmt"] == "csv"
    csv_text = csv_ret["data"]
    assert "content" in csv_text.splitlines()[0]
    assert "导出测试" in csv_text

    bad = _r(srv.export_memories(fmt="xml"))
    assert bad["ok"] is False


def test_ttl_and_purge(srv):
    # #6 TTL:过期的记忆检索时被忽略,可清理。
    # 正向:ttl_seconds 写入未来的 expires_at。
    mid = _id(srv.add_memory(content="临时便签", user_id="u1", ttl_seconds=3600))
    got = srv._collection.get(ids=[mid], include=["metadatas"])
    assert got["metadatas"][0]["expires_at"] > 0
    # 手动把它改成已过期(模拟时间流逝),再验证被忽略/清理。
    meta = got["metadatas"][0]
    meta["expires_at"] = 1.0  # 远古时间 => 已过期
    srv._collection.update(ids=[mid], metadatas=[meta])
    srv.add_memory(content="长期偏好", user_id="u1", force=True)

    res = _r(srv.search_memories(query="便签", user_id="u1"))
    assert not any("临时便签" in c for c in _contents(res["items"]))
    listed = _r(srv.get_memories(user_id="u1"))
    assert not any("临时便签" in c for c in _contents(listed["items"]))
    purged = _r(srv.purge_expired())
    assert purged["ok"] is True
    assert purged["deleted"] == 1


def test_scope_not_duplicated(srv):
    # #5 一条记忆关联多作用域,不复制副本。
    srv.add_memory(content="共享记忆", user_id="u1", agent_id="a1")
    from_u = _r(srv.get_memories(user_id="u1"))
    from_a = _r(srv.get_memories(agent_id="a1"))
    assert any("共享记忆" in c for c in _contents(from_u["items"]))
    assert any("共享记忆" in c for c in _contents(from_a["items"]))
    assert srv._collection.count() == 1


# ---------------------------------------------------------------------------
# 客户端连接测试
#
# db.py 已简化为纯客户端模式(MEMORY_CHROMA_URL 连接外部后端)。
# pytest 下 _init_client 走嵌入式 PersistentClient 以保证隔离与速度。
# ---------------------------------------------------------------------------


def test_connect_returns_none_when_no_backend(srv):
    # _connect 连不上应快速返回 None,不抛异常。
    assert srv._connect("127.0.0.1", _free_port()) is None
