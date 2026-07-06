"""TTL、过期、清理相关。"""

from conftest import r, get_id, contents


def test_update_ttl_renew_and_clear(srv):
    mid = get_id(srv.add_memory(content="临时", user_id="u1", ttl_seconds=3600))
    # 清除过期 -> 变永久
    srv.update_memory(mid, ttl_seconds=-1)
    meta = srv._collection.get(ids=[mid], include=["metadatas"])["metadatas"][0]
    assert not meta.get("expires_at")
    assert not srv._is_expired(meta)
    # 重新续期
    srv.update_memory(mid, ttl_seconds=7200)
    meta = srv._collection.get(ids=[mid], include=["metadatas"])["metadatas"][0]
    assert meta["expires_at"] > 0
    # ttl_seconds=0 不动过期,但仍能改文本
    srv.update_memory(mid, content="改了文本")
    meta = srv._collection.get(ids=[mid], include=["metadatas"])["metadatas"][0]
    assert meta["expires_at"] > 0


def test_search_overfetch_past_expired(srv):
    # 即使前面挤了很多过期项,有效项仍能被返回
    for i in range(30):
        mid = get_id(srv.add_memory(content=f"过期便签 {i}", user_id="u1",
                                    force=True, ttl_seconds=3600))
        g = srv._collection.get(ids=[mid], include=["metadatas"])
        m = g["metadatas"][0]
        m["expires_at"] = 1.0
        srv._collection.update(ids=[mid], metadatas=[m])
    srv.add_memory(content="这是唯一有效的便签", user_id="u1", force=True)
    res = r(srv.search_memories(query="便签", user_id="u1", limit=5))
    cs = contents(res["items"])
    assert any("这是唯一有效的便签" in c for c in cs)
    assert not any("过期便签" in c for c in cs)


def test_ttl_and_purge(srv):
    mid = get_id(srv.add_memory(content="临时便签", user_id="u1", ttl_seconds=3600))
    got = srv._collection.get(ids=[mid], include=["metadatas"])
    assert got["metadatas"][0]["expires_at"] > 0
    # 模拟过期
    meta = got["metadatas"][0]
    meta["expires_at"] = 1.0
    srv._collection.update(ids=[mid], metadatas=[meta])
    srv.add_memory(content="长期偏好", user_id="u1", force=True)

    res = r(srv.search_memories(query="便签", user_id="u1"))
    assert not any("临时便签" in c for c in contents(res["items"]))
    listed = r(srv.get_memories(user_id="u1"))
    assert not any("临时便签" in c for c in contents(listed["items"]))
    purged = r(srv.purge_expired())
    assert purged["deleted"] == 1
