"""lm-mem server 的单元/集成测试。

用临时目录作为 ChromaDB 落盘路径,避免污染真实记忆库。
运行:  uv run pytest -q
"""

import importlib
import json
import os
import sys
import tempfile

import pytest


@pytest.fixture()
def srv():
    """每个测试用独立的临时 DB 重新加载 server 模块。"""
    tmp = tempfile.mkdtemp(prefix="lm-mem-test-")
    os.environ["MEMORY_DB_PATH"] = tmp
    sys.modules.pop("server", None)
    module = importlib.import_module("server")
    module = importlib.reload(module)
    yield module


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
    assert "总记忆数: 2" in stats
    assert "pref=2" in stats
    assert "category" in stats


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
