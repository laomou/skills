"""backend 客户端连接测试。"""


def test_connect_returns_none_when_no_backend(srv, free_port):
    # _connect 连不上应快速返回 None,不抛异常
    assert srv._connect("127.0.0.1", free_port) is None
