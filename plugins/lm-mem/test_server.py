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
import time

import pytest

# 共享后端相关环境变量:每个 srv 测试前清空,避免用例间互相污染。
_BACKEND_ENV = (
    "MEMORY_CHROMA_HOST",
    "MEMORY_CHROMA_PORT",
    "MEMORY_CHROMA_URL",
)


@pytest.fixture()
def srv():
    """每个测试用独立的临时 DB 重新加载 server 模块(默认嵌入式)。

    同时清除 db 模块缓存,确保 _collection 指向临时 DB 而非上一轮测试的连接。
    """
    tmp = tempfile.mkdtemp(prefix="lm-mem-test-")
    os.environ["MEMORY_DB_PATH"] = tmp
    for key in _BACKEND_ENV:
        os.environ.pop(key, None)
    for mod_name in ("server", "mcp_tools", "db", "helpers"):
        sys.modules.pop(mod_name, None)
    module = importlib.import_module("server")
    module = importlib.reload(module)
    yield module


def _free_port():
    """取一个当前空闲的本地端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _kill_chroma_on(port):
    """清理监听指定端口的 chroma 后端进程(尽力而为)。

    后端可能以 `chroma run ... --port N` 或回退的 `python -c "..." run ... --port N`
    形式启动,故按 `--port N` 匹配命令行,覆盖两种情况。
    """
    import subprocess

    try:
        out = subprocess.run(
            ["pgrep", "-f", f"run .*--port {port}"],
            capture_output=True, text=True,
        )
        for pid in out.stdout.split():
            subprocess.run(["kill", pid], capture_output=True)
        time.sleep(0.5)  # 给 uvicorn 一点退出时间
    except Exception:
        pass


def _id_from(msg):
    # "已保存记忆 id=<uuid>"
    return msg.split("id=", 1)[1].strip()


def test_add_and_get(srv):
    out = srv.add_memory(content="用户喜欢简洁的回答", user_id="u1")
    assert "已保存记忆" in out
    mem_id = _id_from(out)
    got = srv.get_memory(mem_id)
    assert "用户喜欢简洁的回答" in got
    assert "u1" in got


def test_semantic_search_finds_paraphrase(srv):
    # #1 语义检索:用词不同也应命中。
    srv.add_memory(content="用户偏好简短的答复", user_id="u1")
    res = srv.search_memories(query="这个人喜不喜欢啰嗦的长篇大论", user_id="u1")
    assert "简短" in res


def test_dedup_blocks_similar(srv):
    # #2 去重:高度相似不插入。
    srv.add_memory(content="我最喜欢的语言是 Python", user_id="u1")
    dup = srv.add_memory(content="我最喜欢的语言是 Python", user_id="u1")
    assert "疑似重复" in dup
    # force 可强制新增
    forced = srv.add_memory(content="我最喜欢的语言是 Python", user_id="u1", force=True)
    assert "已保存记忆" in forced


def test_dedup_scoped_per_user(srv):
    # 不同作用域不应互相触发去重。
    srv.add_memory(content="喜欢深色主题", user_id="u1")
    other = srv.add_memory(content="喜欢深色主题", user_id="u2")
    assert "已保存记忆" in other


def test_metadata_store_and_filter(srv):
    # #3 自定义 metadata + 过滤。
    srv.add_memory(
        content="部署用 Kubernetes",
        user_id="u1",
        metadata=json.dumps({"category": "infra", "importance": "high"}),
    )
    srv.add_memory(content="午饭吃了面", user_id="u1",
                   metadata=json.dumps({"category": "misc"}))
    res = srv.search_memories(
        query="部署方案", user_id="u1",
        metadata_filter=json.dumps({"category": "infra"}),
    )
    assert "Kubernetes" in res
    assert "面" not in res
    listed = srv.get_memories(user_id="u1",
                              metadata_filter=json.dumps({"category": "misc"}))
    assert "面" in listed
    assert "Kubernetes" not in listed


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
    out = srv.add_memory(messages=msgs, user_id="u1")
    assert "已保存记忆" in out
    res = srv.search_memories(query="用户在哪个城市", user_id="u1")
    assert "上海" in res


def test_empty_input_rejected(srv):
    assert "拒绝执行" in srv.add_memory()


def test_update_content_and_metadata(srv):
    mid = _id_from(srv.add_memory(content="旧内容", user_id="u1",
                                  metadata=json.dumps({"category": "a"})))
    srv.update_memory(mid, content="新内容", metadata=json.dumps({"importance": "low"}))
    got = srv.get_memory(mid)
    assert "新内容" in got
    assert "importance" in got
    assert "category" in got  # 原有 metadata 保留


def test_stats(srv):
    # #6 统计。
    srv.add_memory(content="a", user_id="u1", tags="pref",
                   metadata=json.dumps({"category": "x"}))
    srv.add_memory(content="b", user_id="u1", tags="pref", force=True,
                   metadata=json.dumps({"category": "y"}))
    stats = srv.memory_stats(user_id="u1")
    assert "有效记忆数: 2" in stats
    assert "总计: 2" in stats
    assert "pref=2" in stats
    assert "category" in stats


def test_stats_excludes_expired_from_aggregates(srv):
    # #1 修复:过期项不计入有效数/标签/分类聚合,只体现在"已过期"。
    srv.add_memory(content="有效", user_id="u1", tags="live")
    mid = _id_from(srv.add_memory(content="过期", user_id="u1", tags="dead",
                                  force=True, ttl_seconds=3600))
    g = srv._collection.get(ids=[mid], include=["metadatas"])
    meta = g["metadatas"][0]
    meta["expires_at"] = 1.0
    srv._collection.update(ids=[mid], metadatas=[meta])
    stats = srv.memory_stats(user_id="u1")
    assert "有效记忆数: 1" in stats
    assert "已过期(待清理): 1" in stats
    assert "总计: 2" in stats
    assert "live=1" in stats
    assert "dead" not in stats  # 过期标签不计入聚合


def test_update_ttl_renew_and_clear(srv):
    # #2 增强:update_memory 可续期与清除过期。
    mid = _id_from(srv.add_memory(content="临时", user_id="u1", ttl_seconds=3600))
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
        mid = _id_from(srv.add_memory(content=f"过期便签 {i}", user_id="u1",
                                      force=True, ttl_seconds=3600))
        g = srv._collection.get(ids=[mid], include=["metadatas"])
        m = g["metadatas"][0]
        m["expires_at"] = 1.0
        srv._collection.update(ids=[mid], metadatas=[m])
    srv.add_memory(content="这是唯一有效的便签", user_id="u1", force=True)
    res = srv.search_memories(query="便签", user_id="u1", limit=5)
    assert "这是唯一有效的便签" in res
    assert "过期便签" not in res


def test_export_json_and_csv(srv):
    srv.add_memory(content="导出测试", user_id="u1",
                   metadata=json.dumps({"category": "z"}))
    js = srv.export_memories(fmt="json", user_id="u1")
    data = json.loads(js)
    assert data[0]["content"] == "导出测试"
    assert data[0]["metadata"]["category"] == "z"
    csv_out = srv.export_memories(fmt="csv", user_id="u1")
    assert "content" in csv_out.splitlines()[0]
    assert "导出测试" in csv_out
    assert "无效" in srv.export_memories(fmt="xml")


def test_ttl_and_purge(srv):
    # #6 TTL:过期的记忆检索时被忽略,可清理。
    # 正向:ttl_seconds 写入未来的 expires_at。
    out = srv.add_memory(content="临时便签", user_id="u1", ttl_seconds=3600)
    mid = _id_from(out)
    got = srv._collection.get(ids=[mid], include=["metadatas"])
    assert got["metadatas"][0]["expires_at"] > 0
    # 手动把它改成已过期(模拟时间流逝),再验证被忽略/清理。
    meta = got["metadatas"][0]
    meta["expires_at"] = 1.0  # 远古时间 => 已过期
    srv._collection.update(ids=[mid], metadatas=[meta])
    srv.add_memory(content="长期偏好", user_id="u1", force=True)

    res = srv.search_memories(query="便签", user_id="u1")
    assert "临时便签" not in res
    listed = srv.get_memories(user_id="u1")
    assert "临时便签" not in listed
    purged = srv.purge_expired()
    assert "1 条" in purged


def test_scope_not_duplicated(srv):
    # #5 一条记忆关联多作用域,不复制副本。
    srv.add_memory(content="共享记忆", user_id="u1", agent_id="a1")
    from_u = srv.get_memories(user_id="u1")
    from_a = srv.get_memories(agent_id="a1")
    assert "共享记忆" in from_u
    assert "共享记忆" in from_a
    assert srv._collection.count() == 1


# ---------------------------------------------------------------------------
# 共享后端相关测试
#
# 生产默认即共享后端;pytest 下 _init_client 默认走嵌入式以保证隔离与速度。
# 故这里直接调用 _ensure_backend 等底层函数来验证后端行为。
# ---------------------------------------------------------------------------


def test_connect_returns_none_when_no_backend(srv):
    # _connect 连不上应快速返回 None,不抛异常。
    assert srv._connect("127.0.0.1", _free_port()) is None


def test_backend_lazy_spawn(srv):
    # _ensure_backend 首次调用应自动 spawn 后端,返回可用 client。
    port = _free_port()
    tmp = tempfile.mkdtemp(prefix="lm-mem-be-")
    try:
        client = srv._ensure_backend("127.0.0.1", port, tmp)
        # 端口上应有 spawn 出来的后端在监听(区别于嵌入式)。
        assert srv._connect("127.0.0.1", port) is not None
        col = client.get_or_create_collection("memories",
                                              metadata={"hnsw:space": "cosine"})
        col.add(ids=["x1"], documents=["经由共享后端保存"])
        assert col.count() == 1
    finally:
        _kill_chroma_on(port)


def test_backend_reuse_existing(srv):
    # 已有后端时,第二次 _ensure_backend 应复用,并能看到已有数据(索引不分叉)。
    port = _free_port()
    tmp = tempfile.mkdtemp(prefix="lm-mem-be-")
    try:
        c1 = srv._ensure_backend("127.0.0.1", port, tmp)
        c1.get_or_create_collection("memories").add(
            ids=["a1"], documents=["第一实例写入"])
        c2 = srv._ensure_backend("127.0.0.1", port, tmp)  # 复用,不新起
        assert srv._connect("127.0.0.1", port) is not None
        assert c2.get_or_create_collection("memories").count() == 1
    finally:
        _kill_chroma_on(port)


def test_backend_explicit_url_no_spawn_raises(srv):
    # explicit_url=True 且后端不存在:应报错,且不 spawn。
    port = _free_port()
    tmp = tempfile.mkdtemp(prefix="lm-mem-be-")
    with pytest.raises(RuntimeError):
        srv._ensure_backend("127.0.0.1", port, tmp, explicit_url=True)
    # 确认没有残留 spawn 出来的后端。
    assert srv._connect("127.0.0.1", port) is None


def test_backend_fallback_embedded_when_spawn_fails(srv, monkeypatch):
    # 后端始终起不来时,_ensure_backend 应回退嵌入式 PersistentClient,不抛异常。
    port = _free_port()
    tmp = tempfile.mkdtemp(prefix="lm-mem-be-")
    import db as _db_mod

    monkeypatch.setattr(_db_mod, "_spawn_chroma", lambda *a, **k: None)  # 让 spawn 无效
    client = _db_mod._ensure_backend("127.0.0.1", port, tmp, wait_seconds=1.0)
    # 回退后仍可正常建集合读写。
    col = client.get_or_create_collection("memories")
    col.add(ids=["f1"], documents=["兜底可用"])
    assert col.count() == 1
    assert _db_mod._connect("127.0.0.1", port) is None  # 确认没有真起后端
