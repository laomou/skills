"""增删改查 + not_found 异常。"""

import json
import pytest

from conftest import r, get_id


def test_add_and_get(srv):
    mem_id = get_id(srv.add_memory(content="用户喜欢简洁的回答", user_id="u1"))
    got = r(srv.get_memory(mem_id))
    assert got["content"] == "用户喜欢简洁的回答"
    assert got["scope"]["user_id"] == "u1"


def test_dedup_blocks_similar(srv):
    srv.add_memory(content="我最喜欢的语言是 Python", user_id="u1")
    dup = r(srv.add_memory(content="我最喜欢的语言是 Python", user_id="u1"))
    # 查重命中是业务分支,不抛异常
    assert "duplicate_id" in dup
    assert dup["similarity"] >= 0.85
    # force 可强制新增
    forced = r(srv.add_memory(content="我最喜欢的语言是 Python", user_id="u1", force=True))
    assert "id" in forced


def test_dedup_scoped_per_user(srv):
    srv.add_memory(content="喜欢深色主题", user_id="u1")
    other = r(srv.add_memory(content="喜欢深色主题", user_id="u2"))
    assert "id" in other


def test_scope_not_duplicated(srv):
    srv.add_memory(content="共享记忆", user_id="u1", agent_id="a1")
    from_u = r(srv.get_memories(user_id="u1"))
    from_a = r(srv.get_memories(agent_id="a1"))
    from conftest import contents as _contents
    assert any("共享记忆" in c for c in _contents(from_u["items"]))
    assert any("共享记忆" in c for c in _contents(from_a["items"]))
    assert srv._collection.count() == 1


def test_update_content_and_metadata(srv):
    mid = get_id(srv.add_memory(content="旧内容", user_id="u1",
                                metadata=json.dumps({"category": "a"})))
    r(srv.update_memory(mid, content="新内容", metadata=json.dumps({"importance": "low"})))
    got = r(srv.get_memory(mid))
    assert got["content"] == "新内容"
    assert got["metadata"]["importance"] == "low"
    assert got["metadata"]["category"] == "a"  # 原有 metadata 保留


def test_get_memory_not_found_raises(srv):
    with pytest.raises(ValueError, match="未找到"):
        srv.get_memory("nonexistent-id")


def test_delete_memory_not_found_raises(srv):
    with pytest.raises(ValueError, match="未找到"):
        srv.delete_memory("nonexistent-id")


def test_delete_all_requires_scope(srv):
    with pytest.raises(ValueError, match="作用域"):
        srv.delete_all_memories()


def test_empty_input_rejected(srv):
    with pytest.raises(ValueError, match="content|messages"):
        srv.add_memory()


def test_bad_metadata_rejected(srv):
    with pytest.raises(ValueError):
        srv.add_memory(content="x", metadata="not-json")
    with pytest.raises(ValueError):
        srv.add_memory(content="x", metadata="[1,2,3]")  # 非对象
