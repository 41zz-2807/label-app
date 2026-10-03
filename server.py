#!/usr/bin/env python3
"""Server aplikasi cetak label.

- Menyajikan file statis dari folder ./static
- REST API sederhana di /api/* dengan database SQLite
- Hanya memakai pustaka standar Python (tanpa pip install)
"""
import json
import mimetypes
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE = Path(__file__).resolve().parent
STATIC = (BASE / "static").resolve()
DB_PATH = os.environ.get("DB_PATH", str(BASE / "data" / "labels.db"))
PORT = int(os.environ.get("PORT", "8010"))
MAX_BODY = 64 * 1024 * 1024  # 64 MB
MAX_ROWS = 200_000

mimetypes.add_type("application/javascript", ".js")

SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datasets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    columns    TEXT NOT NULL,
    rows       TEXT NOT NULL,
    row_count  INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    printed_at    TEXT NOT NULL,
    template_name TEXT NOT NULL DEFAULT '',
    dataset_name  TEXT NOT NULL DEFAULT '',
    total_labels  INTEGER NOT NULL DEFAULT 0,
    pages         INTEGER NOT NULL DEFAULT 0,
    page_desc     TEXT NOT NULL DEFAULT ''
);
"""


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.commit()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def clean_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, "Nama wajib diisi.")
    name = value.strip()
    if len(name) > 120:
        raise ApiError(400, "Nama maksimal 120 karakter.")
    return name


def to_int(value, default=0):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- handlers
def templates_list(conn):
    rows = conn.execute(
        "SELECT id, name, updated_at FROM templates ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [dict(r) for r in rows]


def templates_get(conn, rid):
    r = conn.execute("SELECT * FROM templates WHERE id=?", (rid,)).fetchone()
    if not r:
        raise ApiError(404, "Templat tidak ditemukan.")
    return {"id": r["id"], "name": r["name"], "updated_at": r["updated_at"],
            "data": json.loads(r["data"])}


def templates_save(conn, body):
    name = clean_name(body.get("name"))
    data = body.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list) \
            or not isinstance(data.get("page"), dict) or not isinstance(data.get("label"), dict):
        raise ApiError(400, "Data templat tidak valid.")
    ts = now()
    conn.execute(
        """INSERT INTO templates (name, data, created_at, updated_at) VALUES (?,?,?,?)
           ON CONFLICT(name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
        (name, json.dumps(data, ensure_ascii=False), ts, ts),
    )
    rid = conn.execute("SELECT id FROM templates WHERE name=?", (name,)).fetchone()["id"]
    return {"id": rid, "name": name}


def datasets_list(conn):
    rows = conn.execute(
        "SELECT id, name, row_count, updated_at FROM datasets ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [dict(r) for r in rows]


def datasets_get(conn, rid):
    r = conn.execute("SELECT * FROM datasets WHERE id=?", (rid,)).fetchone()
    if not r:
        raise ApiError(404, "Data tidak ditemukan.")
    return {"id": r["id"], "name": r["name"], "row_count": r["row_count"],
            "columns": json.loads(r["columns"]), "rows": json.loads(r["rows"])}


def datasets_save(conn, body):
    name = clean_name(body.get("name"))
    columns = body.get("columns")
    rows = body.get("rows")
    if not isinstance(columns, list) or not columns or len(columns) > 300 \
            or not all(isinstance(c, str) for c in columns):
        raise ApiError(400, "Daftar kolom tidak valid.")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS \
            or not all(isinstance(r, list) for r in rows):
        raise ApiError(400, "Baris data tidak valid (maksimal %d baris)." % MAX_ROWS)
    ts = now()
    conn.execute(
        """INSERT INTO datasets (name, columns, rows, row_count, created_at, updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(name) DO UPDATE SET columns=excluded.columns, rows=excluded.rows,
               row_count=excluded.row_count, updated_at=excluded.updated_at""",
        (name, json.dumps(columns, ensure_ascii=False),
         json.dumps(rows, ensure_ascii=False), len(rows), ts, ts),
    )
    rid = conn.execute("SELECT id FROM datasets WHERE name=?", (name,)).fetchone()["id"]
    return {"id": rid, "name": name, "row_count": len(rows)}


def history_list(conn):
    rows = conn.execute("SELECT * FROM history ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(r) for r in rows]


def history_add(conn, body):
    conn.execute(
        """INSERT INTO history (printed_at, template_name, dataset_name, total_labels, pages, page_desc)
           VALUES (?,?,?,?,?,?)""",
        (now(), str(body.get("template_name") or "")[:120], str(body.get("dataset_name") or "")[:120],
         to_int(body.get("total_labels")), to_int(body.get("pages")),
         str(body.get("page_desc") or "")[:200]),
    )
    # simpan maksimal 1000 riwayat terakhir
    conn.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 1000)")
    return {"ok": True}


def delete_row(conn, table, rid):
    cur = conn.execute("DELETE FROM %s WHERE id=?" % table, (rid,))
    if cur.rowcount == 0:
        raise ApiError(404, "Data tidak ditemukan.")
    return {"ok": True}


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "LabelApp/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers
    def send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = to_int(self.headers.get("Content-Length"))
        if length > MAX_BODY:
            raise ApiError(413, "Data terlalu besar (maksimal 64 MB).")
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise ApiError(400, "Format JSON tidak valid.")
        if not isinstance(data, dict):
            raise ApiError(400, "Body harus berupa objek JSON.")
        return data

    # -- API routing
    def api(self, method, path):
        parts = [p for p in path[len("/api/"):].split("/") if p]
        if not parts:
            raise ApiError(404, "Endpoint tidak ditemukan.")
        res = parts[0]
        rid = parts[1] if len(parts) > 1 else None
        if rid is not None and not rid.isdigit():
            raise ApiError(404, "ID tidak valid.")
        rid = int(rid) if rid is not None else None

        if res == "health" and method == "GET":
            return {"ok": True}

        body = self.read_json() if method == "POST" else None
        with closing(connect()) as conn:
            with conn:  # commit / rollback otomatis
                if res in ("templates", "datasets"):
                    lst, get, save = ((templates_list, templates_get, templates_save)
                                      if res == "templates"
                                      else (datasets_list, datasets_get, datasets_save))
                    if method == "GET" and rid is None:
                        return lst(conn)
                    if method == "GET":
                        return get(conn, rid)
                    if method == "POST" and rid is None:
                        return save(conn, body)
                    if method == "DELETE" and rid is not None:
                        return delete_row(conn, res, rid)
                elif res == "history":
                    if method == "GET" and rid is None:
                        return history_list(conn)
                    if method == "POST" and rid is None:
                        return history_add(conn, body)
                    if method == "DELETE" and rid is None:
                        conn.execute("DELETE FROM history")
                        return {"ok": True}
        raise ApiError(404, "Endpoint tidak ditemukan.")

    def handle_api(self, method):
        path = urlparse(self.path).path
        try:
            self.send_json(200, self.api(method, path))
        except ApiError as e:
            self.send_json(e.status, {"error": e.message})
        except sqlite3.Error as e:
            sys.stderr.write("SQLite error: %s\n" % e)
            self.send_json(500, {"error": "Kesalahan database."})
        except Exception as e:  # noqa: BLE001
            sys.stderr.write("Error: %r\n" % e)
            self.send_json(500, {"error": "Kesalahan server."})

    # -- static files
    def serve_static(self, head_only=False):
        path = unquote(urlparse(self.path).path)
        if path == "/":
            path = "/index.html"
        target = (STATIC / path.lstrip("/")).resolve()
        if STATIC not in target.parents or not target.is_file():
            body = b"Not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
            return
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if "vendor" in target.parts:
            self.send_header("Cache-Control", "public, max-age=86400")
        else:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    # -- verbs
    def do_GET(self):
        if self.path.startswith("/api/"):
            self.handle_api("GET")
        else:
            self.serve_static()

    def do_HEAD(self):
        if self.path.startswith("/api/"):
            self.send_json(405, {"error": "Method tidak didukung."})
        else:
            self.serve_static(head_only=True)

    def do_POST(self):
        if self.path.startswith("/api/"):
            self.handle_api("POST")
        else:
            self.send_json(405, {"error": "Method tidak didukung."})

    def do_DELETE(self):
        if self.path.startswith("/api/"):
            self.handle_api("DELETE")
        else:
            self.send_json(405, {"error": "Method tidak didukung."})


def main():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("Aplikasi label berjalan di http://0.0.0.0:%d  (database: %s)" % (PORT, DB_PATH), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
