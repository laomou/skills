"""语义检索 + metadata_filter + messages 输入。"""

import json

from conftest import r, contents


def test_semantic_search_finds_paraphrase(srv):
    srv.add_memory(content="用户偏好简短的答复", user_id="u1")
    res = r(srv.search_memories(query="这个人喜不喜欢啰嗦的长篇大论", user_id="u1"))
    assert any("简短" in c for c in contents(res["items"]))


def test_metadata_store_and_filter(srv):
    srv.add_memory(
        content="部署用 Kubernetes",
        user_id="u1",
        metadata=json.dumps({"category": "infra", "importance": "high"}),
    )
    srv.add_memory(content="午饭吃了面", user_id="u1",
                   metadata=json.dumps({"category": "misc"}))
    res = r(srv.search_memories(
        query="部署方案", user_id="u1",
        metadata_filter=json.dumps({"category": "infra"}),
    ))
    cs = contents(res["items"])
    assert any("Kubernetes" in c for c in cs)
    assert not any("面" in c for c in cs)
    listed = r(srv.get_memories(user_id="u1",
                                metadata_filter=json.dumps({"category": "misc"})))
    cs = contents(listed["items"])
    assert any("面" in c for c in cs)
    assert not any("Kubernetes" in c for c in cs)


def test_messages_input(srv):
    msgs = json.dumps([
        {"role": "user", "content": "我住在上海"},
        {"role": "assistant", "content": "记住了"},
    ])
    out = r(srv.add_memory(messages=msgs, user_id="u1"))
    assert "id" in out
    res = r(srv.search_memories(query="用户在哪个城市", user_id="u1"))
    assert any("上海" in c for c in contents(res["items"]))
