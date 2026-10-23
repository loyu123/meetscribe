"""U2：索引分词版本元信息与「需重建索引」判定。"""
import search
import store


def test_meta_defaults_without_index(db):
    search.init_search_db()
    m = search.index_meta()
    assert m["tokenize_version"] == search.TOKENIZE_VERSION
    assert m["index_tokenize_version"] is None
    assert m["needs_reindex"] is False  # 无索引/无版本记录时不做误报


def test_stale_version_needs_reindex(db):
    search.init_search_db()
    rid = "rid-u2-stale"
    with store.conn() as c:
        c.execute("DELETE FROM search_chunks WHERE recording_id=?", (rid,))
        c.execute("INSERT INTO search_chunks(recording_id,search_text) VALUES(?,?)",
                  (rid, "张伟说下周一交付"))
    try:
        search._meta_set("tokenize_version", search.TOKENIZE_VERSION - 1)
        m = search.index_meta()
        assert m["index_tokenize_version"] == search.TOKENIZE_VERSION - 1
        assert m["needs_reindex"] is True
        # 版本跟上后提示消失
        search._meta_set("tokenize_version", search.TOKENIZE_VERSION)
        assert search.index_meta()["needs_reindex"] is False
    finally:
        with store.conn() as c:
            c.execute("DELETE FROM search_chunks WHERE recording_id=?", (rid,))
        search._meta_set("tokenize_version", search.TOKENIZE_VERSION)


def test_search_response_carries_meta(client):
    body = client.post("/api/v1/search", json={"query": "张伟"}).get_json()
    assert body["meta"]["tokenize_version"] == search.TOKENIZE_VERSION
    assert "needs_reindex" in body["meta"]
