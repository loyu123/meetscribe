"""S2：媒体路径约束——库内路径指向数据目录外时必须 404。"""
import os

import config


def _seed_recording(db, rid, path):
    db.init_db()
    with db.conn() as c:
        c.execute("INSERT INTO recordings(id, filename, status, path, created_at) "
                  "VALUES(?, 'x.wav', 'done', ?, '2026-01-01 00:00:00')", (rid, path))


def test_outside_path_blocked(client, db, tmp_path):
    """path 指向数据目录外的真实文件 → 404（任意文件读取面封死）。"""
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    _seed_recording(db, "r-out", str(secret))
    r = client.get("/api/v1/recordings/r-out/media")
    assert r.status_code == 404


def test_inside_path_served(client, db, tmp_path):
    """path 位于数据目录内 → 正常返回文件内容。"""
    inside = os.path.join(config.AUDIO_DIR, "inner.wav")
    os.makedirs(config.AUDIO_DIR, exist_ok=True)
    with open(inside, "wb") as f:
        f.write(b"RIFF-fake-wav")
    _seed_recording(db, "r-in", inside)
    r = client.get("/api/v1/recordings/r-in/media")
    assert r.status_code == 200
    assert b"RIFF-fake-wav" in r.data


def test_missing_file_404(client, db, tmp_path):
    """库内路径但文件不存在 → 404。"""
    _seed_recording(db, "r-miss", os.path.join(config.AUDIO_DIR, "nope.wav"))
    assert client.get("/api/v1/recordings/r-miss/media").status_code == 404


def test_traversal_via_symlink_style_path(client, db, tmp_path):
    """../ 形式的越界路径同样被 realpath 拦截。"""
    _seed_recording(db, "r-trav", os.path.join(config.AUDIO_DIR, "..", "secret.txt"))
    assert client.get("/api/v1/recordings/r-trav/media").status_code == 404
