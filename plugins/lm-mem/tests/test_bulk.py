"""统计 + 导出/导入 + 用户上下文。"""

import json
import pytest

from conftest import r, get_id, contents


# ── stats ────────────────────────────────────────────


def test_stats(srv):
    srv.add_memory(content="a", user_id="u1", tags="pref",
                   metadata=json.dumps({"category": "x"}))
    srv.add_memory(content="b", user_id="u1", tags="pref", force=True,
                   metadata=json.dumps({"category": "y"}))
    stats = r(srv.memory_stats(user_id="u1"))
    assert stats["counts"]["active"] == 2
    assert stats["counts"]["total"] == 2
    assert stats["counts"]["expired"] == 0
    assert stats["tags"]["pref"] == 2
    assert stats["categories"]["x"] == 1
    assert stats["categories"]["y"] == 1


def test_stats_excludes_expired_from_aggregates(srv):
    srv.add_memory(content="有效", user_id="u1", tags="live")
    mid = get_id(srv.add_memory(content="过期", user_id="u1", tags="dead",
                                force=True, ttl_seconds=3600))
    g = srv._collection.get(ids=[mid], include=["metadatas"])
    meta = g["metadatas"][0]
    meta["expires_at"] = 1.0
    srv._collection.update(ids=[mid], metadatas=[meta])
    stats = r(srv.memory_stats(user_id="u1"))
    assert stats["counts"]["active"] == 1
    assert stats["counts"]["expired"] == 1
    assert stats["counts"]["total"] == 2
    assert stats["tags"].get("live") == 1
    assert "dead" not in stats["tags"]  # 过期标签不计入聚合


# ── export / import roundtrip ────────────────────────


def test_export_json_and_csv(srv):
    srv.add_memory(content="导出测试", user_id="u1",
                   metadata=json.dumps({"category": "z"}))
    js = r(srv.export_memories(fmt="json", user_id="u1"))
    assert js["records"][0]["content"] == "导出测试"
    assert js["records"][0]["metadata"]["category"] == "z"

    csv_ret = r(srv.export_memories(fmt="csv", user_id="u1"))
    csv_text = csv_ret["csv"]
    assert "content" in csv_text.splitlines()[0]
    assert "导出测试" in csv_text

    with pytest.raises(ValueError, match="fmt"):
        srv.export_memories(fmt="xml")


def test_import_json_roundtrip(srv):
    srv.add_memory(content="A", user_id="u1", tags="x",
                   metadata=json.dumps({"category": "pref"}))
    srv.add_memory(content="B", user_id="u1", tags="y",
                   metadata=json.dumps({"category": "decision"}))
    exp = r(srv.export_memories(fmt="json", user_id="u1"))
    srv.delete_all_memories(user_id="u1")
    assert srv._collection.count() == 0

    imp = r(srv.import_memories(data=json.dumps(exp["records"]), fmt="json"))
    assert imp["imported"] == 2
    assert imp["skipped"] == 0

    listed = r(srv.get_memories(user_id="u1"))
    cs = contents(listed["items"])
    assert "A" in cs
    assert "B" in cs


def test_import_csv_roundtrip(srv):
    srv.add_memory(content="记忆内容", user_id="u1", tags="a",
                   metadata=json.dumps({"category": "pref"}))
    exp = r(srv.export_memories(fmt="csv", user_id="u1"))
    srv.delete_all_memories(user_id="u1")
    imp = r(srv.import_memories(data=exp["csv"], fmt="csv"))
    assert imp["imported"] == 1
    listed = r(srv.get_memories(user_id="u1"))
    assert contents(listed["items"]) == ["记忆内容"]
    assert listed["items"][0]["metadata"]["category"] == "pref"


def test_import_skips_duplicates_by_default(srv):
    srv.add_memory(content="旧", user_id="u1")
    exp = r(srv.export_memories(fmt="json", user_id="u1"))
    imp = r(srv.import_memories(data=json.dumps(exp["records"])))
    assert imp["imported"] == 0
    assert imp["skipped"] == 1
    assert srv._collection.count() == 1


def test_import_overwrite(srv):
    srv.add_memory(content="旧内容", user_id="u1")
    exp = r(srv.export_memories(fmt="json", user_id="u1"))
    records = exp["records"]
    records[0]["content"] = "新内容"
    imp = r(srv.import_memories(data=json.dumps(records), overwrite=True))
    assert imp["overwritten"] == 1
    got = r(srv.get_memory(records[0]["id"]))
    assert got["content"] == "新内容"


def test_import_new_ids(srv):
    srv.add_memory(content="X", user_id="u1")
    exp = r(srv.export_memories(fmt="json", user_id="u1"))
    imp = r(srv.import_memories(data=json.dumps(exp["records"]), new_ids=True))
    assert imp["imported"] == 1
    assert srv._collection.count() == 2  # 原来的 + 新的


def test_import_invalid(srv):
    with pytest.raises(ValueError, match="fmt"):
        srv.import_memories(data="[]", fmt="yaml")
    with pytest.raises(ValueError, match="JSON"):
        srv.import_memories(data="not-json", fmt="json")
    with pytest.raises(ValueError, match="互斥"):
        srv.import_memories(data="[]", overwrite=True, new_ids=True)


# ── get_user_context ─────────────────────────────────


def test_get_user_context_returns_core_categories(srv):
    srv.add_memory(content="偏好 pytest", user_id="u1",
                   metadata=json.dumps({"category": "preference", "importance": "high"}))
    srv.add_memory(content="Go 工程师", user_id="u1",
                   metadata=json.dumps({"category": "identity", "importance": "medium"}))
    srv.add_memory(content="Mac M1", user_id="u1",
                   metadata=json.dumps({"category": "environment", "importance": "low"}))
    srv.add_memory(content="上次的方案", user_id="u1",
                   metadata=json.dumps({"category": "episode"}))  # 不应返回

    ctx = r(srv.get_user_context(user_id="u1"))
    cs = contents(ctx["items"])
    assert any("pytest" in c for c in cs)
    assert any("Go" in c for c in cs)
    assert any("Mac" in c for c in cs)
    assert not any("上次" in c for c in cs)  # episode 排除
    # importance:high 排最前
    assert "pytest" in ctx["items"][0]["content"]


def test_get_user_context_respects_user_scope(srv):
    srv.add_memory(content="u1 偏好", user_id="u1",
                   metadata=json.dumps({"category": "preference"}))
    srv.add_memory(content="u2 偏好", user_id="u2",
                   metadata=json.dumps({"category": "preference"}))
    ctx = r(srv.get_user_context(user_id="u1"))
    cs = contents(ctx["items"])
    assert any("u1" in c for c in cs)
    assert not any("u2" in c for c in cs)
