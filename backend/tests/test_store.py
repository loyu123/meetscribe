"""存储层单元测试：ai_jobs 生命周期、索引状态、复核确认的租户防护。"""
import sqlite3


def test_ai_job_lifecycle(db):
    db.ai_job_upsert("polish", "r1", "", status="processing")
    j = db.ai_job_get("polish", "r1", "")
    assert j and j["status"] == "processing"

    db.ai_job_upsert("polish", "r1", "", status="done", result_json='{"ok":1}')
    j = db.ai_job_get("polish", "r1", "")
    assert j["status"] == "done" and j["result_json"] == '{"ok":1}'

    db.ai_job_del("polish", "r1", "")
    assert db.ai_job_get("polish", "r1", "") is None


def test_ai_job_cleanup_stale(db):
    db.ai_job_upsert("summary", "r2", "meeting", status="processing")
    # 固定为远 past 时间戳，规避本地时区与 UTC cutoff 的格式差异
    with db.conn() as c:
        c.execute("UPDATE ai_jobs SET updated_at='2000-01-01 00:00:00' WHERE recording_id='r2'")
    n = db.ai_job_cleanup_stale(max_hours=6)
    assert n >= 1
    assert db.ai_job_get("summary", "r2", "meeting")["status"] == "failed"


def test_set_index_status_done_sets_timestamp(db):
    db.init_db()
    with db.conn() as c:
        c.execute("INSERT INTO recordings(id, filename, status, created_at) "
                  "VALUES('ridx','f.wav','done','2026-01-01 00:00:00')")
    db.set_index_status("ridx", "indexing")
    with db.conn() as c:
        row = c.execute("SELECT index_status, indexed_at FROM recordings WHERE id='ridx'").fetchone()
    assert row["index_status"] == "indexing" and row["indexed_at"] is None

    db.set_index_status("ridx", "done")
    with db.conn() as c:
        row = c.execute("SELECT index_status, indexed_at FROM recordings WHERE id='ridx'").fetchone()
    assert row["index_status"] == "done" and row["indexed_at"]


def _seed_review_data(db):
    """造 录音→任务→低置信度分片 一条链，返回 (segment_id, rid)。"""
    import uuid
    db.init_db()
    rid, jid = uuid.uuid4().hex[:12], uuid.uuid4().hex[:12]
    with db.conn() as c:
        c.execute("INSERT INTO recordings(id, filename, status, created_at) "
                  "VALUES(?, 'f1.wav','done','2026-01-01 00:00:00')", (rid,))
        c.execute("INSERT INTO jobs(id, recording_id, status, created_at) "
                  "VALUES(?, ?,'done','2026-01-01 00:00:00')", (jid, rid))
        c.execute("INSERT INTO segments(job_id, chunk_idx, local_spk, start_ms, end_ms, "
                  "text, confidence, need_review, review_reason) "
                  "VALUES(?, 0, 0, 0, 1000, '你好', 0.4, 1, '低置信度')", (jid,))
        return c.execute("SELECT last_insert_rowid() id").fetchone()[0], rid


def test_review_list_and_filters(db):
    sid, _rid = _seed_review_data(db)
    res = db.list_review_segments()
    assert res["total"] >= 1 and any(s["id"] == sid for s in res["items"])
    low = db.list_review_segments(conf_max=0.6)
    assert any(s["id"] == sid for s in low["items"])
    high = db.list_review_segments(conf_max=0.3)
    assert not any(s["id"] == sid for s in high["items"])


def test_confirm_tenant_guard(db):
    sid, rid = _seed_review_data(db)
    # 不允许任何录音 → 不确认
    assert db.confirm_review_segments([sid], allowed_recording_ids=[]) == 0
    # 仍待复核
    assert db.list_review_segments()["total"] >= 1
    # 允许其录音 → 确认
    assert db.confirm_review_segments([sid], allowed_recording_ids=[rid]) == 1
    with db.conn() as c:
        row = c.execute("SELECT need_review FROM segments WHERE id=?", (sid,)).fetchone()
    assert row["need_review"] == 0
