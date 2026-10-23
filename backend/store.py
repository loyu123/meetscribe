"""SQLite 存储层：recordings / jobs / chunks / segments / chunk_speakers / events。

设计为每次操作打开独立连接（WAL），可安全地被 Flask 请求线程与后台 worker 并发使用。
"""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
  id TEXT PRIMARY KEY,
  filename TEXT,
  ext TEXT,
  path TEXT,
  bytes INTEGER,
  duration_ms INTEGER,
  num_speakers INTEGER,
  status TEXT,
  error TEXT,
  created_at TEXT,
  deleted_at REAL,
  folder TEXT DEFAULT '',
  index_status TEXT DEFAULT 'none',  -- none/indexing/done/failed（P0-2 搜索索引异步化）
  indexed_at TEXT,
  index_error TEXT
);
CREATE TABLE IF NOT EXISTS folders (
  name TEXT PRIMARY KEY,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS templates (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  color TEXT DEFAULT '#2b5cff',
  description TEXT DEFAULT '',
  sections TEXT DEFAULT '[]',
  opts TEXT DEFAULT '{}',
  builtin INTEGER DEFAULT 0,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  recording_id TEXT,
  status TEXT,
  stage TEXT,
  progress REAL DEFAULT 0,
  total_chunks INTEGER DEFAULT 0,
  done_chunks INTEGER DEFAULT 0,
  failed_chunks INTEGER DEFAULT 0,
  hotword TEXT,
  preset_spk_num INTEGER,
  asr_model TEXT,
  denoise INTEGER DEFAULT 0,
  callback_url TEXT,
  result_path TEXT,
  error TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  idx INTEGER,
  start_ms INTEGER,
  end_ms INTEGER,
  status TEXT,
  attempts INTEGER DEFAULT 0,
  error TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  chunk_idx INTEGER,
  start_ms INTEGER,
  end_ms INTEGER,
  text TEXT,
  local_spk INTEGER,
  global_spk INTEGER,
  need_review INTEGER DEFAULT 0,
  review_reason TEXT,
  confidence REAL,
  words TEXT
);
CREATE TABLE IF NOT EXISTS idempotency (
  key TEXT PRIMARY KEY,
  recording_id TEXT,
  job_id TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS chunk_speakers (
  job_id TEXT,
  chunk_idx INTEGER,
  local_spk INTEGER,
  centroid BLOB,
  PRIMARY KEY (job_id, chunk_idx, local_spk)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  ts TEXT,
  kind TEXT,
  detail TEXT
);
CREATE TABLE IF NOT EXISTS summaries (
  id TEXT PRIMARY KEY,
  recording_id TEXT,
  job_id TEXT,
  template TEXT,
  model TEXT,
  version TEXT,
  content TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS summary_edits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  summary_id TEXT,
  editor TEXT,
  before_text TEXT,
  after_text TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS ai_jobs (
  kind TEXT NOT NULL,            -- 'summary' | 'polish'
  recording_id TEXT NOT NULL,
  template TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,          -- processing / done / failed
  error TEXT,
  result_json TEXT,              -- polish 完成结果（重启后不丢）
  summary_id TEXT,
  model TEXT,
  version TEXT,
  updated_at TEXT,
  PRIMARY KEY (kind, recording_id, template)
);
CREATE INDEX IF NOT EXISTS idx_chunks_job ON chunks(job_id);
CREATE INDEX IF NOT EXISTS idx_segments_job ON segments(job_id);
"""


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        yield c
        c.commit()
    finally:
        c.close()


_MIGRATIONS = [
    ("jobs", "asr_model", "TEXT"),
    ("jobs", "denoise", "INTEGER DEFAULT 0"),
    ("segments", "need_review", "INTEGER DEFAULT 0"),
    ("segments", "review_reason", "TEXT"),
    ("segments", "confidence", "REAL"),
    ("segments", "words", "TEXT"),
    ("recordings", "tenant_id", "TEXT DEFAULT ''"),
    ("recordings", "deleted_at", "REAL"),
    ("recordings", "folder", "TEXT DEFAULT ''"),
    ("jobs", "tenant_id", "TEXT DEFAULT ''"),
    ("summaries", "tenant_id", "TEXT DEFAULT ''"),
    ("summaries", "stale", "INTEGER DEFAULT 0"),
    ("recordings", "index_status", "TEXT DEFAULT 'none'"),
    ("recordings", "indexed_at", "TEXT"),
    ("recordings", "index_error", "TEXT"),
]


def init_db():
    config.ensure_dirs()
    with conn() as c:
        c.executescript(_SCHEMA)
        for table, col, typ in _MIGRATIONS:
            cols = [r["name"] for r in c.execute("PRAGMA table_info(%s)" % table).fetchall()]
            if col not in cols:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))
    ensure_default_folders()
    seed_templates()
    recover_interrupted()


# ---------------- templates（纪要模板：内置 + 自定义，可自定义章节与提取指导语） ----------------
_BUILTIN_TEMPLATES = [
    ("meeting", "会议纪要", "#2b5cff", "主题、参与人、要点、行动项。适合日常例会、评审会。",
     [{"title": "讨论要点", "hint": "按议题提取讨论中的关键信息、结论与数据。"}],
     {"timestamps": 1, "todos": 1, "formal": 1}),
    ("memo", "个人备忘", "#0f9d6b", "单人视角的要点与待办，适合一对一沟通、任务交底。",
     [{"title": "要点", "hint": "以备忘人视角提取与自己相关的信息。"}],
     {"timestamps": 1, "todos": 1, "formal": 0}),
]


def seed_templates():
    """首次启动播种两个内置模板；用户删除自定义模板不会复活，内置始终保留。"""
    with conn() as c:
        for tid, name, color, desc, secs, opts in _BUILTIN_TEMPLATES:
            c.execute(
                "INSERT OR IGNORE INTO templates(id,name,color,description,sections,opts,builtin,created_at) "
                "VALUES(?,?,?,?,?,?,1,?)",
                (tid, name, color, desc, json.dumps(secs, ensure_ascii=False),
                 json.dumps(opts), now()),
            )


def list_templates():
    with conn() as c:
        rows = c.execute("SELECT * FROM templates ORDER BY builtin DESC, created_at").fetchall()
        out = []
        for x in rows:
            d = dict(x)
            d["sections"] = json.loads(d["sections"] or "[]")
            d["opts"] = json.loads(d["opts"] or "{}")
            d["builtin"] = bool(d["builtin"])
            out.append(d)
        return out


def get_template(tid):
    with conn() as c:
        x = c.execute("SELECT * FROM templates WHERE id=?", (tid,)).fetchone()
        if not x:
            return None
        d = dict(x)
        d["sections"] = json.loads(d["sections"] or "[]")
        d["opts"] = json.loads(d["opts"] or "{}")
        d["builtin"] = bool(d["builtin"])
        return d


def create_template(name, color="#2b5cff", description="", sections=None, opts=None):
    """创建自定义模板，返回 (id, error)。"""
    name = (name or "").strip()
    if not name:
        return None, "模板名称不能为空"
    if len(name) > 30:
        return None, "模板名称过长（最多 30 字）"
    sections = sections or []
    if not isinstance(sections, list) or not (1 <= len(sections) <= 12):
        return None, "章节需 1~12 个"
    for s in sections:
        if not isinstance(s, dict) or not (s.get("title") or "").strip():
            return None, "章节标题不能为空"
    tid = uuid.uuid4().hex
    with conn() as c:
        c.execute(
            "INSERT INTO templates(id,name,color,description,sections,opts,builtin,created_at) "
            "VALUES(?,?,?,?,?,?,0,?)",
            (tid, name, color or "#2b5cff", (description or "").strip(),
             json.dumps(sections, ensure_ascii=False), json.dumps(opts or {}), now()),
        )
    return tid, None


def update_template(tid, name, color, description, sections, opts):
    """编辑模板（内置模板仅允许调整颜色与说明），返回 error。"""
    t = get_template(tid)
    if not t:
        return "模板不存在"
    if not t["builtin"]:
        name = (name or "").strip()
        if not name:
            return "模板名称不能为空"
        if not isinstance(sections, list) or not (1 <= len(sections) <= 12):
            return "章节需 1~12 个"
        for s in sections:
            if not isinstance(s, dict) or not (s.get("title") or "").strip():
                return "章节标题不能为空"
    with conn() as c:
        if t["builtin"]:
            c.execute("UPDATE templates SET color=?, description=? WHERE id=?",
                      (color or t["color"], (description or "").strip(), tid))
        else:
            c.execute("UPDATE templates SET name=?,color=?,description=?,sections=?,opts=? WHERE id=?",
                      (name.strip(), color or t["color"], (description or "").strip(),
                       json.dumps(sections, ensure_ascii=False), json.dumps(opts or {}), tid))
    return None


def delete_template(tid):
    """删除自定义模板；内置模板与被纪要引用的模板不可删。返回 error。"""
    t = get_template(tid)
    if not t:
        return "模板不存在"
    if t["builtin"]:
        return "内置模板不可删除，可复制为自定义模板后修改"
    with conn() as c:
        used = c.execute("SELECT COUNT(*) AS n FROM summaries WHERE template=?", (tid,)).fetchone()["n"]
        if used:
            return "该模板已生成过 %d 份纪要，暂不能删除" % used
        c.execute("DELETE FROM templates WHERE id=?", (tid,))
    return None


def recover_interrupted():
    """启动时恢复被中断的任务：进程重启会把正在识别的分片留在 processing 状态，
    而 worker 只认 pending/failed 分片与 queued 任务，不恢复则永远卡住。
    将孤儿 processing 分片重置为 pending、任务重置为 queued，由 worker 重新领取
    （已完成的分片自动跳过，只补跑未完成部分）。"""
    with conn() as c:
        n1 = c.execute("UPDATE chunks SET status='pending' WHERE status='processing'").rowcount
        n2 = c.execute(
            "UPDATE jobs SET status='queued', stage='排队中', error=NULL WHERE status='processing'"
        ).rowcount
    if n1 or n2:
        print("[recover] 重启恢复：分片 %d 个、任务 %d 个已重新入队" % (n1, n2))


# ---------------- folders（动态文件夹：除「全部录音」外的可建删目录） ----------------
def ensure_default_folders():
    """首次使用时播种默认文件夹（表为空才播种，删除后不会复活）。"""
    with conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM folders").fetchone()["n"]
        if n == 0:
            for name in ("项目复盘", "客户访谈"):
                c.execute("INSERT OR IGNORE INTO folders(name) VALUES(?)", (name,))


def list_folders():
    """返回 [{name, count}]，count 为未删除录音数。"""
    with conn() as c:
        rows = c.execute(
            "SELECT f.name AS name, COUNT(r.id) AS count FROM folders f "
            "LEFT JOIN recordings r ON r.folder=f.name AND r.deleted_at IS NULL "
            "GROUP BY f.name ORDER BY f.name"
        ).fetchall()
        return [dict(x) for x in rows]


def create_folder(name):
    """创建文件夹，返回 (name, error)。"""
    name = (name or "").strip()
    if not name:
        return None, "文件夹名不能为空"
    if len(name) > 30:
        return None, "文件夹名过长（最多 30 字）"
    with conn() as c:
        if c.execute("SELECT 1 FROM folders WHERE name=?", (name,)).fetchone():
            return None, "文件夹「%s」已存在" % name
        c.execute("INSERT INTO folders(name, created_at) VALUES(?, ?)", (name, now()))
    return name, None


def delete_folder(name):
    """删除文件夹；其中未删除的录音移至未归类，返回移动条数。"""
    with conn() as c:
        moved = c.execute(
            "UPDATE recordings SET folder='' WHERE folder=? AND deleted_at IS NULL", (name,)
        ).rowcount
        c.execute("DELETE FROM folders WHERE name=?", (name,))
    return moved


# ---------------- recordings ----------------
def create_recording(rid, filename, ext, path, nbytes, duration_ms=0, num_speakers=None,
                     tenant_id=""):
    with conn() as c:
        c.execute(
            "INSERT INTO recordings(id,filename,ext,path,bytes,duration_ms,num_speakers,"
            "status,created_at,tenant_id)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (rid, filename, ext, path, nbytes, duration_ms, num_speakers, "queued", now(),
             tenant_id or ""),
        )


def set_recording_status(rid, status, duration_ms=None, num_speakers=None, error=None):
    with conn() as c:
        c.execute(
            "UPDATE recordings SET status=?, duration_ms=COALESCE(?,duration_ms),"
            " num_speakers=COALESCE(?,num_speakers), error=? WHERE id=?",
            (status, duration_ms, num_speakers, error, rid),
        )


def get_recording(rid):
    with conn() as c:
        r = c.execute("SELECT * FROM recordings WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None


# ---------------- 索引状态（P0-2 搜索索引异步化） ----------------
def set_index_status(rid, status, error=None):
    """更新录音检索索引状态：none / indexing / done / failed。done 时记录 indexed_at。"""
    with conn() as c:
        if status == "done":
            c.execute("UPDATE recordings SET index_status='done', indexed_at=?, index_error=NULL WHERE id=?",
                      (now(), rid))
        else:
            c.execute("UPDATE recordings SET index_status=?, index_error=? WHERE id=?",
                      (status, error, rid))


def count_unindexed(recording_ids=None):
    """统计尚未完成索引的已完成录音数（none/failed，不含 indexing），供前端提示。"""
    sql = "SELECT COUNT(*) n FROM recordings WHERE status IN ('done','partial') " \
          "AND (index_status IS NULL OR index_status IN ('none','failed')) AND deleted_at IS NULL"
    params = []
    if recording_ids is not None:
        if not recording_ids:
            return 0
        sql += " AND id IN (%s)" % ",".join("?" for _ in recording_ids)
        params.extend(recording_ids)
    with conn() as c:
        return c.execute(sql, params).fetchone()["n"]


def list_recordings(limit=100, tenant_id=None, deleted=False):
    # 默认只返回未删除（回收站数据用 deleted=True 单独取）
    cond = "r.deleted_at IS NOT NULL" if deleted else "r.deleted_at IS NULL"
    with conn() as c:
        if tenant_id is not None:
            # 租户可见：自身租户 + 未分配(共享) 的录音
            rows = c.execute(
                "SELECT r.*, j.id AS job_id, j.status AS job_status, j.progress AS job_progress "
                "FROM recordings r LEFT JOIN jobs j ON j.recording_id=r.id "
                "WHERE (r.tenant_id=? OR r.tenant_id='') AND %s "
                "ORDER BY r.created_at DESC LIMIT ?" % cond,
                (tenant_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT r.*, j.id AS job_id, j.status AS job_status, j.progress AS job_progress "
                "FROM recordings r LEFT JOIN jobs j ON j.recording_id=r.id "
                "WHERE %s ORDER BY r.created_at DESC LIMIT ?" % cond,
                (limit,),
            ).fetchall()
        return [dict(x) for x in rows]


def list_recording_ids(tenant_id=None, folder=None):
    """返回某租户可见的录音 id 集合（供检索按租户隔离过滤，不含回收站）。

    P1-4：folder 传 '' 表示未归档，传具体名表示该文件夹；None 不过滤。
    """
    with conn() as c:
        sql, params = "SELECT id FROM recordings WHERE deleted_at IS NULL", []
        if tenant_id is not None:
            sql += " AND (tenant_id=? OR tenant_id='')"
            params.append(tenant_id)
        if folder is not None:
            sql += " AND COALESCE(folder,'')=?"
            params.append(folder)
        rows = c.execute(sql, params).fetchall()
        return {r["id"] for r in rows}


def soft_delete_recording(rid):
    """移入回收站（默认删除动作，7 天内可恢复）。"""
    with conn() as c:
        c.execute("UPDATE recordings SET deleted_at=? WHERE id=?", (time.time(), rid))


def list_expired_deleted(days=7):
    """回收站中超过 days 天的录音（供后台自动清理）。"""
    cutoff = time.time() - days * 86400
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM recordings WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff,)).fetchall()
        return [dict(x) for x in rows]


def restore_recording(rid):
    """从回收站恢复。"""
    with conn() as c:
        c.execute("UPDATE recordings SET deleted_at=NULL WHERE id=?", (rid,))


def set_recording_folder(rid, folder):
    """移动录音到文件夹（'' 表示不归类）。"""
    with conn() as c:
        c.execute("UPDATE recordings SET folder=? WHERE id=?", (folder or "", rid))


def delete_recording(rid):
    with conn() as c:
        job = c.execute("SELECT id FROM jobs WHERE recording_id=?", (rid,)).fetchone()
        jid = job["id"] if job else None
        if jid:
            # 注意：jobs 表主键是 id，其余表用 job_id 关联
            for t in ("chunks", "segments", "chunk_speakers", "events"):
                c.execute("DELETE FROM %s WHERE job_id=?" % t, (jid,))
            c.execute("DELETE FROM jobs WHERE id=?", (jid,))
        # FR-34 删除闭环：级联清理摘要与编辑留痕，避免孤儿记录
        sids = [r["id"] for r in c.execute(
            "SELECT id FROM summaries WHERE recording_id=?", (rid,)).fetchall()]
        for sid in sids:
            c.execute("DELETE FROM summary_edits WHERE summary_id=?", (sid,))
        c.execute("DELETE FROM summaries WHERE recording_id=?", (rid,))
        # 清理指向该录音的幂等映射，防止重传同文件时命中已删除的旧任务
        c.execute("DELETE FROM idempotency WHERE recording_id=?", (rid,))
        c.execute("DELETE FROM recordings WHERE id=?", (rid,))
        return jid


# ---------------- jobs ----------------
def create_job(jid, recording_id, hotword="", preset_spk_num=None, callback_url=None,
               asr_model="paraformer", denoise=0):
    with conn() as c:
        c.execute(
            "INSERT INTO jobs(id,recording_id,status,stage,progress,hotword,preset_spk_num,"
            "asr_model,denoise,callback_url,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (jid, recording_id, "queued", "排队中", 0, hotword, preset_spk_num,
             asr_model, denoise, callback_url, now(), now()),
        )


def get_job(jid):
    with conn() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return dict(r) if r else None


def get_job_by_recording(rid):
    with conn() as c:
        r = c.execute(
            "SELECT * FROM jobs WHERE recording_id=? ORDER BY created_at DESC LIMIT 1", (rid,)
        ).fetchone()
        return dict(r) if r else None


def update_job(jid, **kw):
    if not kw:
        return
    kw["updated_at"] = now()
    cols = ",".join("%s=?" % k for k in kw)
    with conn() as c:
        c.execute("UPDATE jobs SET %s WHERE id=?" % cols, list(kw.values()) + [jid])


def claim_next_job():
    """原子地取出一个排队中的任务并置为 processing。"""
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        r = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not r:
            return None
        c.execute("UPDATE jobs SET status='processing',stage='准备中',updated_at=? WHERE id=?", (now(), r["id"]))
        return dict(r)


def peek_queued(limit=1):
    """查看排队中的任务（不领取），供按租户并发限流判断。limit>1 时返回多个候选，
    worker 可跳过已达并发上限的租户，避免队头阻塞整个队列。"""
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT ?", (limit,)
        ).fetchall()
        return [dict(x) for x in rows]


def claim_job(jid):
    """原子地领取指定任务（仅当仍为 queued）。返回 dict 或 None。"""
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        r = c.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()
        if not r or r["status"] != "queued":
            return None
        c.execute("UPDATE jobs SET status='processing',stage='准备中',updated_at=? WHERE id=?", (now(), jid))
        row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return dict(row)


def requeue_job(jid):
    """把 processing 中的任务放回队列（worker 领取后放弃处理的兜底路径）。"""
    with conn() as c:
        c.execute("UPDATE jobs SET status='queued', stage='排队中', updated_at=? WHERE id=? AND status='processing'",
                  (now(), jid))


# ---------------- chunks ----------------
def create_chunks(jid, ranges):
    with conn() as c:
        c.executemany(
            "INSERT INTO chunks(job_id,idx,start_ms,end_ms,status,attempts,updated_at) VALUES(?,?,?,?,?,0,?)",
            [(jid, i, s, e, "pending", now()) for i, (s, e) in enumerate(ranges)],
        )
        c.execute("UPDATE jobs SET total_chunks=?,progress=0 WHERE id=?", (len(ranges), jid))


def get_chunks(jid):
    with conn() as c:
        rows = c.execute("SELECT * FROM chunks WHERE job_id=? ORDER BY idx", (jid,)).fetchall()
        return [dict(x) for x in rows]


def pending_chunks(jid):
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM chunks WHERE job_id=? AND status IN ('pending','failed') ORDER BY idx", (jid,)
        ).fetchall()
        return [dict(x) for x in rows]


def latest_result_job(rid):
    """取该录音最新一个已产出转写结果的 job。"""
    with conn() as c:
        r = c.execute(
            "SELECT * FROM jobs WHERE recording_id=? AND result_path IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1", (rid,)).fetchone()
        return dict(r) if r else None


def update_segment_text(jid, start_ms, end_ms, text):
    """按时间范围定位一个 turn 覆盖的全部 segment：首条写新文本，其余置空
    （一句 turn 可能由多条相邻 segment 合并而成，只更新首条会把旧文本残留在检索索引里）。"""
    with conn() as c:
        n = c.execute(
            "UPDATE segments SET text=? WHERE job_id=? AND start_ms=?", (text, jid, start_ms)
        ).rowcount
        if end_ms:
            c.execute(
                "UPDATE segments SET text='' WHERE job_id=? AND start_ms>? AND start_ms<?",
                (jid, start_ms, end_ms),
            )
        return n


def set_chunk_status(jid, idx, status, error=None, inc_attempt=False):
    with conn() as c:
        c.execute(
            "UPDATE chunks SET status=?, error=?, attempts=attempts+?, updated_at=? WHERE job_id=? AND idx=?",
            (status, error, 1 if inc_attempt else 0, now(), jid, idx),
        )


def refresh_job_progress(jid):
    with conn() as c:
        done = c.execute("SELECT COUNT(*) n FROM chunks WHERE job_id=? AND status='done'", (jid,)).fetchone()["n"]
        failed = c.execute("SELECT COUNT(*) n FROM chunks WHERE job_id=? AND status='failed'", (jid,)).fetchone()["n"]
        total = c.execute("SELECT COUNT(*) n FROM chunks WHERE job_id=?", (jid,)).fetchone()["n"]
        progress = round(done * 100.0 / total, 1) if total else 0
        c.execute(
            "UPDATE jobs SET done_chunks=?,failed_chunks=?,progress=?,updated_at=? WHERE id=?",
            (done, failed, progress, now(), jid),
        )
        return {"done": done, "failed": failed, "total": total, "progress": progress}


def reset_failed_chunks(jid):
    """把失败/卡死的分片（failed 及上次崩溃遗留的 processing）重置为 pending。"""
    with conn() as c:
        cur = c.execute(
            "UPDATE chunks SET status='pending', error=NULL"
            " WHERE job_id=? AND status IN ('failed','processing')", (jid,)
        )
        return cur.rowcount


def split_failed_chunk(jid, idx, n):
    """把分片 idx 对半切（或均分 n 份），原始行保留为第 1 段，其余新行追加到其后。

    通过把 idx > idx 的分片整体后移 (n-1) 腾出空位，保证 idx 仍按时间单调递增，
    下游聚类（按 idx 顺序）与 segments（按 start_ms）不受影响。
    返回全部新分片的 idx 列表（含原 idx）。
    """
    n = max(2, int(n))
    with conn() as c:
        ch = c.execute(
            "SELECT start_ms,end_ms FROM chunks WHERE job_id=? AND idx=?", (jid, idx)
        ).fetchone()
        if not ch:
            return []
        s, e = ch["start_ms"], ch["end_ms"]
        if e - s <= 0:
            return []
        step = (e - s) // n
        # 腾位：把 idx 之后的所有分片整体后移，避免与新插入的行冲突
        c.execute("UPDATE chunks SET idx=idx+(?) WHERE job_id=? AND idx>?", (n - 1, jid, idx))
        # 原始行保留为第 1 段（first half），重置为待处理
        c.execute(
            "UPDATE chunks SET end_ms=?, status='pending', error=NULL, attempts=0, updated_at=?"
            " WHERE job_id=? AND idx=?", (s + step, now(), jid, idx)
        )
        new_idxs = [idx]
        for i in range(1, n):
            ss = s + i * step
            ee = e if i == n - 1 else s + (i + 1) * step
            ni = idx + i  # 空位已由上面的移位让出
            c.execute(
                "INSERT INTO chunks(job_id,idx,start_ms,end_ms,status,attempts,updated_at)"
                " VALUES(?,?,?,?,?,0,?)", (jid, ni, ss, ee, "pending", now())
            )
            new_idxs.append(ni)
    return new_idxs


# ---------------- segments / speakers ----------------
def clear_chunk_segments(jid, chunk_idx):
    with conn() as c:
        c.execute("DELETE FROM segments WHERE job_id=? AND chunk_idx=?", (jid, chunk_idx))
        c.execute("DELETE FROM chunk_speakers WHERE job_id=? AND chunk_idx=?", (jid, chunk_idx))


def add_chunk_segments(jid, chunk_idx, sentences):
    with conn() as c:
        c.executemany(
            "INSERT INTO segments(job_id,chunk_idx,start_ms,end_ms,text,local_spk,global_spk,"
            "need_review,review_reason,confidence,words) VALUES(?,?,?,?,?,?,NULL,?,?,?,?)",
            [(jid, chunk_idx, s["start_ms"], s["end_ms"], s["text"], s["local_spk"],
              s.get("need_review", 0), s.get("review_reason", ""),
              s.get("confidence"), json.dumps(s["words"], ensure_ascii=False) if s.get("words") else None)
             for s in sentences],
        )


def add_chunk_speaker(jid, chunk_idx, local_spk, centroid):
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO chunk_speakers(job_id,chunk_idx,local_spk,centroid) VALUES(?,?,?,?)",
            (jid, chunk_idx, local_spk, centroid),
        )


def get_all_centroids(jid):
    """返回 [(chunk_idx, local_spk, np.ndarray)]，按 chunk/spk 排序保证顺序稳定。"""
    import numpy as np

    with conn() as c:
        rows = c.execute(
            "SELECT chunk_idx,local_spk,centroid FROM chunk_speakers WHERE job_id=? ORDER BY chunk_idx,local_spk",
            (jid,),
        ).fetchall()
    out = []
    for r in rows:
        try:
            out.append((r["chunk_idx"], r["local_spk"], np.frombuffer(r["centroid"], dtype=np.float32)))
        except Exception:
            pass
    return out


def set_segments_global_spk(jid, mapping):
    """mapping: {(chunk_idx, local_spk): global_spk}"""
    with conn() as c:
        rows = c.execute("SELECT id,chunk_idx,local_spk FROM segments WHERE job_id=?", (jid,)).fetchall()
        for r in rows:
            g = mapping.get((r["chunk_idx"], r["local_spk"]))
            c.execute("UPDATE segments SET global_spk=? WHERE id=?", (g, r["id"]))


def get_segments(jid):
    with conn() as c:
        rows = c.execute("SELECT * FROM segments WHERE job_id=? ORDER BY start_ms,id", (jid,)).fetchall()
        return [dict(x) for x in rows]


def list_review_segments(limit=200, tenant_id=None):
    """全局复核队列：所有被标记需人工复核的句子（FR-17）；可按租户隔离。"""
    with conn() as c:
        if tenant_id is not None:
            rows = c.execute(
                "SELECT s.*, j.recording_id, j.asr_model FROM segments s "
                "JOIN jobs j ON j.id=s.job_id "
                "JOIN recordings r ON r.id=j.recording_id "
                "WHERE s.need_review=1 AND (r.tenant_id=? OR r.tenant_id='') "
                "ORDER BY j.updated_at DESC, s.start_ms LIMIT ?", (tenant_id, limit)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT s.*, j.recording_id, j.asr_model FROM segments s JOIN jobs j ON j.id=s.job_id "
                "WHERE s.need_review=1 ORDER BY j.updated_at DESC, s.start_ms LIMIT ?", (limit,)
            ).fetchall()
    return [dict(x) for x in rows]


def confirm_review_segments(ids):
    """批量人工确认：need_review 置 0 并清除原因，句子从复核队列消失。返回确认条数。"""
    vals = []
    for x in (ids or [])[:500]:
        try:
            vals.append(int(x))
        except (TypeError, ValueError):
            continue
    if not vals:
        return 0
    with conn() as c:
        cur = c.execute(
            "UPDATE segments SET need_review=0, review_reason=NULL "
            "WHERE id IN (%s)" % ",".join("?" * len(vals)),
            vals,
        )
        return cur.rowcount


# ---------------- summaries（FR-19~FR-24） ----------------
def save_summary(rid, jid, template, model, version, content, tenant_id=""):
    sid = uuid.uuid4().hex
    with conn() as c:
        c.execute(
            "INSERT INTO summaries(id,recording_id,job_id,template,model,version,content,created_at,tenant_id)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (sid, rid, jid, template, model, version,
             json.dumps(content, ensure_ascii=False), now(), tenant_id or ""),
        )
    return sid


def get_summary_by_id(sid):
    with conn() as c:
        r = c.execute("SELECT * FROM summaries WHERE id=?", (sid,)).fetchone()
        return dict(r) if r else None


def mark_summaries_stale(rid):
    """FR-24：转写重新完成后，将该录音已有摘要标记为失效（基于旧转写）。"""
    with conn() as c:
        c.execute("UPDATE summaries SET stale=1 WHERE recording_id=?", (rid,))


# ---------------- ai_jobs（纪要/润色任务状态持久化，重启不丢） ----------------
def ai_job_upsert(kind, rid, template="", **fields):
    """写入/更新一条 AI 任务状态。fields 可含 status/error/result_json/summary_id/model/version。"""
    with conn() as c:
        c.execute(
            "INSERT INTO ai_jobs(kind,recording_id,template,status,error,result_json,"
            "summary_id,model,version,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(kind,recording_id,template) DO UPDATE SET "
            "status=excluded.status,error=excluded.error,result_json=excluded.result_json,"
            "summary_id=excluded.summary_id,model=excluded.model,version=excluded.version,"
            "updated_at=excluded.updated_at",
            (kind, rid, template, fields.get("status", "processing"),
             fields.get("error"), fields.get("result_json"),
             fields.get("summary_id"), fields.get("model"), fields.get("version"), now()),
        )


def ai_job_get(kind, rid, template=""):
    with conn() as c:
        r = c.execute(
            "SELECT * FROM ai_jobs WHERE kind=? AND recording_id=? AND template=?",
            (kind, rid, template),
        ).fetchone()
        return dict(r) if r else None


def ai_job_del(kind, rid, template=""):
    with conn() as c:
        c.execute("DELETE FROM ai_jobs WHERE kind=? AND recording_id=? AND template=?",
                  (kind, rid, template))


def ai_job_cleanup_stale(max_hours=6):
    """启动时调用：把残留的 processing 任务标记为 failed（服务重启即中断）。"""
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - max_hours * 3600))
    with conn() as c:
        n = c.execute(
            "UPDATE ai_jobs SET status='failed', error='服务重启导致任务中断，请重新生成', "
            "updated_at=? WHERE status='processing' AND updated_at < ?",
            (now(), cutoff),
        ).rowcount
        # 更保守兜底：最近 6 小时内启动却仍在 processing 的（多半也是重启残留），保留 processing
        # 让前端继续轮询几次后再人工重试；超过 6 小时的必然是僵尸。
    return n


def get_summary(rid, template=None):
    with conn() as c:
        if template:
            r = c.execute(
                "SELECT * FROM summaries WHERE recording_id=? AND template=? "
                "ORDER BY created_at DESC LIMIT 1", (rid, template)
            ).fetchone()
        else:
            r = c.execute(
                "SELECT * FROM summaries WHERE recording_id=? ORDER BY created_at DESC LIMIT 1",
                (rid,)
            ).fetchone()
    if not r:
        return None
    d = dict(r)
    try:
        d["content"] = json.loads(d["content"])
    except Exception:
        d["content"] = {}
    return d


def save_summary_edit(sid, editor, before, after):
    """人工校对留痕（FR-23）。"""
    with conn() as c:
        c.execute(
            "INSERT INTO summary_edits(summary_id,editor,before_text,after_text,created_at)"
            " VALUES(?,?,?,?,?)", (sid, editor or "anonymous", before, after, now())
        )


# ---------------- events ----------------
def add_event(jid, kind, detail=""):
    with conn() as c:
        c.execute("INSERT INTO events(job_id,ts,kind,detail) VALUES(?,?,?,?)", (jid, now(), kind, detail))


# ---------------- 幂等键（FR-06） ----------------
def get_idempotency(key):
    with conn() as c:
        r = c.execute("SELECT * FROM idempotency WHERE key=?", (key,)).fetchone()
        return dict(r) if r else None


def save_idempotency(key, recording_id, job_id):
    with conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO idempotency(key,recording_id,job_id,created_at) VALUES(?,?,?,?)",
            (key, recording_id, job_id, now()),
        )


def delete_idempotency(key):
    with conn() as c:
        c.execute("DELETE FROM idempotency WHERE key=?", (key,))


# ---------------- 可观测性统计 ----------------
def stats_summary(tenant_id=None):
    """队列/状态/失败率/置信度概览（非功能-可观测性）。按租户可选隔离。"""
    today = now()[:10]
    with conn() as c:
        if tenant_id is not None:
            join_where = "WHERE (r.tenant_id=? OR r.tenant_id='') AND r.deleted_at IS NULL"
            rec_args = (tenant_id,)
        else:
            join_where = "WHERE r.deleted_at IS NULL"
            rec_args = ()

        recs = c.execute(
            "SELECT r.status, COUNT(*) n, COALESCE(SUM(r.duration_ms),0) dur "
            "FROM recordings r %s GROUP BY r.status" % join_where, rec_args).fetchall()
        jobs = c.execute(
            "SELECT j.status, COUNT(*) n FROM jobs j JOIN recordings r ON r.id=j.recording_id %s "
            "GROUP BY j.status" % join_where, rec_args).fetchall()
        chunks = c.execute(
            "SELECT ch.status, COUNT(*) n FROM chunks ch "
            "JOIN jobs j ON j.id=ch.job_id JOIN recordings r ON r.id=j.recording_id %s "
            "GROUP BY ch.status" % join_where, rec_args).fetchall()
        seg = c.execute(
            "SELECT COUNT(*) n, AVG(s.confidence) avg_conf, COALESCE(SUM(s.need_review),0) review "
            "FROM segments s JOIN jobs j ON j.id=s.job_id "
            "JOIN recordings r ON r.id=j.recording_id %s" % join_where, rec_args).fetchone()
        if tenant_id is not None:
            tj = c.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN j.status='failed' THEN 1 ELSE 0 END),0) failed "
                "FROM jobs j JOIN recordings r ON r.id=j.recording_id "
                "WHERE (r.tenant_id=? OR r.tenant_id='') AND r.deleted_at IS NULL AND j.created_at LIKE ?",
                (tenant_id, today + "%")).fetchone()
        else:
            tj = c.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN j.status='failed' THEN 1 ELSE 0 END),0) failed "
                "FROM jobs j WHERE j.created_at LIKE ?", (today + "%",)).fetchone()

    n_today = tj["n"] or 0
    failed_today = tj["failed"] or 0
    return {
        "generated_at": now(),
        "recordings": {x["status"]: x["n"] for x in recs},
        "audio_duration_ms_total": sum(x["dur"] for x in recs),
        "jobs": {x["status"]: x["n"] for x in jobs},
        "queue": {
            "queued": {x["status"]: x["n"] for x in jobs}.get("queued", 0),
            "processing": {x["status"]: x["n"] for x in jobs}.get("processing", 0),
        },
        "chunks": {x["status"]: x["n"] for x in chunks},
        "segments": {
            "count": seg["n"],
            "avg_confidence": round(seg["avg_conf"], 4) if seg["avg_conf"] is not None else None,
            "need_review": seg["review"],
        },
        "jobs_today": {
            "count": n_today,
            "failed": failed_today,
            "failure_rate": round(failed_today / n_today, 4) if n_today else 0.0,
        },
    }
