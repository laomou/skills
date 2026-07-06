"""共享 fixture 和辅助函数。

用临时目录作为存储后端落盘路径,避免污染真实记忆库。
"""

import importlib
import json
import os
import socket
import sys
import tempfile
import pytest

_BACKEND_ENV = ("LM_MEM_BACKEND_URL",)


@pytest.fixture()
def srv():
    """每个测试用独立的临时 DB,从 mcp_tools + backend + memory_utils 组合命名空间。"""
    tmp = tempfile.mkdtemp(prefix="lm-mem-test-")
    os.environ["LM_MEM_DB_PATH"] = tmp
    for key in _BACKEND_ENV:
        os.environ.pop(key, None)
    for mod_name in ("mcp_tools", "backend", "memory_utils"):
        sys.modules.pop(mod_name, None)

    import backend as _db
    import memory_utils as _hlp

    _db = importlib.reload(_db)
    _hlp = importlib.reload(_hlp)
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


@pytest.fixture()
def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def r(msg):
    """解析工具返回的 JSON 字符串。"""
    return json.loads(msg)


def get_id(msg):
    return r(msg)["id"]


def contents(items):
    return [it["content"] for it in items]
