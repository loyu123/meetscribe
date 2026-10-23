"""pytest 全局夹具（D1 最小测试集）。

在导入任何应用模块之前，把环境固定到独立临时目录：
- ASR_DB_PATH / ASR_DATA_DIR 指向临时目录，绝不触碰真实数据；
- 默认匿名模式（不配 ASR_API_KEYS），鉴权用例自行临时注入并还原。
"""
import os
import sys
import tempfile

_tmpdir = tempfile.mkdtemp(prefix="meetscribe-test-")
os.environ.setdefault("ASR_DB_PATH", os.path.join(_tmpdir, "test.db"))
os.environ.setdefault("ASR_DATA_DIR", _tmpdir)
os.environ.setdefault("ASR_API_KEYS", "")
os.environ.setdefault("ASR_GATEWAY_URL", "")
os.environ.setdefault("ASR_GATEWAY_TOKEN", "")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import store  # noqa: E402


@pytest.fixture()
def db():
    """每个用例独立的已初始化存储（共享同一临时 DB 文件，表结构幂等）。"""
    store.init_db()
    return store


@pytest.fixture()
def client():
    """Flask 测试客户端（不启动 worker 线程）。"""
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
