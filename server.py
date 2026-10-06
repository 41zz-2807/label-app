#!/usr/bin/env python3
"""Server aplikasi cetak label.

- Menyajikan file statis dari folder ./static
- REST API sederhana di /api/* dengan database SQLite
- Hanya memakai pustaka standar Python (tanpa pip install)
"""
import base64
import binascii
import io
import json
import mimetypes
import os
import sqlite3
import sys
import zipfile
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


def to_float(value, default=0.0):
    try:
        return float(value)
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


# ---------------------------------------------------------------- XLSX
# Penulis .xlsx minimal memakai pustaka standar: gambar label (PNG hasil render
# SVG di browser) ditanamkan sebagai gambar di dalam sel sheet.
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_XLSX_IMAGES = 300
MAX_XLSX_ROWS = 20_000
EMU_PER_MM = 36_000
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

_XL_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFF_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_DRAW_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_ART_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def xml_escape(value):
    """Escape teks untuk XML; buang karakter kontrol yang tidak sah."""
    out = []
    for ch in str(value):
        code = ord(ch)
        if code < 0x20 and ch not in "\t\n":
            continue
        if code == 0x7F:
            continue
        if ch == "&":
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        elif ch == '"':
            out.append("&quot;")
        elif ch == "'":
            out.append("&apos;")
        else:
            out.append(ch)
    return "".join(out)


def col_letter(index):
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        name = chr(65 + rem) + name
    return name


def _cell_xml(ref, value, bold=False):
    style = ' s="1"' if bold else ""
    if isinstance(value, bool):
        return '<c r="%s"%s t="inlineStr"><is><t>%s</t></is></c>' % (ref, style, "TRUE" if value else "FALSE")
    if isinstance(value, (int, float)):
        return '<c r="%s"%s><v>%s</v></c>' % (ref, style, repr(value))
    text = xml_escape(value if value is not None else "")
    return '<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, style, text)


def _sheet_xml(header, rows, col_widths, row_heights, has_drawing):
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<worksheet xmlns="%s" xmlns:r="%s">' % (_XL_NS, _OFF_NS)]
    cols = ['<col min="%d" max="%d" width="%.2f" customWidth="1"/>' % (i + 1, i + 1, w)
            for i, w in enumerate(col_widths)]
    if cols:
        parts.append("<cols>%s</cols>" % "".join(cols))
    parts.append("<sheetData>")
    head_cells = "".join(_cell_xml("%s1" % col_letter(i), h, bold=True) for i, h in enumerate(header))
    parts.append('<row r="1">%s</row>' % head_cells)
    for r, values in enumerate(rows):
        row_no = r + 2
        cells = "".join(_cell_xml("%s%d" % (col_letter(c), row_no), v) for c, v in enumerate(values))
        height = row_heights.get(r)
        attr = ' ht="%.2f" customHeight="1"' % height if height else ""
        parts.append('<row r="%d"%s>%s</row>' % (row_no, attr, cells))
    parts.append("</sheetData>")
    if has_drawing:
        parts.append('<drawing r:id="rId1"/>')
    parts.append("</worksheet>")
    return "".join(parts)


def _drawing_xml(images):
    """images: daftar (row_index_0_based, bytes_png, mm_w, mm_h)."""
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<xdr:wsDr xmlns:xdr="%s" xmlns:a="%s" xmlns:r="%s">' % (_DRAW_NS, _ART_NS, _OFF_NS)]
    for i, (row_index, _png, mm_w, mm_h) in enumerate(images):
        parts.append(
            "<xdr:oneCellAnchor>"
            "<xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff>"
            "<xdr:row>%d</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
            '<xdr:ext cx="%d" cy="%d"/>'
            "<xdr:pic>"
            '<xdr:nvPicPr><xdr:cNvPr id="%d" name="Label %d"/><xdr:cNvPicPr/></xdr:nvPicPr>'
            '<xdr:blipFill><a:blip r:embed="rId%d"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
            '<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
            "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom></xdr:spPr>"
            "</xdr:pic><xdr:clientData/></xdr:oneCellAnchor>"
            % (row_index + 1, EMU_PER_MM * int(round(mm_w)), EMU_PER_MM * int(round(mm_h)),
               i + 1, i + 1, i + 1, EMU_PER_MM * int(round(mm_w)), EMU_PER_MM * int(round(mm_h))))
    parts.append("</xdr:wsDr>")
    return "".join(parts)


def build_xlsx(header, rows, images=(), label_mm=None, sheet_name="Label"):
    """Susun file .xlsx (bytes).

    header : list[str]  judul kolom
    rows   : list[list] nilai sel (selaras dengan header)
    images : list[(row_index_0_based, png_bytes, mm_w, mm_h)]  gambar untuk sel kolom pertama
    """
    images = list(images)
    has_drawing = bool(images)
    mm_w, mm_h = label_mm if label_mm else (0, 0)
    # lebar kolom & tinggi baris supaya kolom gambar +- pas dengan ukuran label
    px_w = mm_w / 25.4 * 96 if mm_w else 0
    px_h = mm_h / 25.4 * 96 if mm_h else 0
    col_widths = [round(px_w / 7.0, 2) if px_w else 12.0] + [14.0] * max(len(header) - 1, 0)
    row_heights = {i: round(px_h * 0.75, 2) for i, _p, _w, _h in images if px_h}

    parts = [
        ("[Content_Types].xml",
         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
         '<Default Extension="xml" ContentType="application/xml"/>'
         '<Default Extension="png" ContentType="image/png"/>'
         '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
         '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
         '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
         + ('<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
            if has_drawing else "") + "</Types>"),
        ("_rels/.rels",
         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="%s">'
         '<Relationship Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/>'
         "</Relationships>" % (_REL_NS, _OFF_NS)),
        ("xl/workbook.xml",
         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<workbook xmlns="%s" xmlns:r="%s"><sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>'
         % (_XL_NS, _OFF_NS, xml_escape(sheet_name))),
        ("xl/_rels/workbook.xml.rels",
         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="%s">'
         '<Relationship Id="rId1" Type="%s/worksheet" Target="worksheets/sheet1.xml"/>'
         '<Relationship Id="rId2" Type="%s/styles" Target="styles.xml"/>'
         "</Relationships>" % (_REL_NS, _OFF_NS, _OFF_NS)),
        ("xl/styles.xml",
         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<styleSheet xmlns="%s">'
         '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
         '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
         '<fills count="2"><fill><patternFill patternType="none"/></fill>'
         '<fill><patternFill patternType="gray125"/></fill></fills>'
         '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
         '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
         '<cellXfs count="2">'
         '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
         '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
         "</cellXfs>"
         '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
         "</styleSheet>" % _XL_NS),
        ("xl/worksheets/sheet1.xml",
         _sheet_xml(header, rows, col_widths, row_heights, has_drawing)),
    ]
    if has_drawing:
        parts.append(("xl/worksheets/_rels/sheet1.xml.rels",
                      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                      '<Relationships xmlns="%s">'
                      '<Relationship Id="rId1" Type="%s/drawing" Target="../drawings/drawing1.xml"/>'
                      "</Relationships>" % (_REL_NS, _OFF_NS)))
        parts.append(("xl/drawings/drawing1.xml", _drawing_xml(images)))
        parts.append(("xl/drawings/_rels/drawing1.xml.rels",
                      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                      '<Relationships xmlns="%s">%s</Relationships>'
                      % (_REL_NS, "".join(
                          '<Relationship Id="rId%d" Type="%s/image" Target="../media/image%d.png"/>'
                          % (i + 1, _OFF_NS, i + 1) for i in range(len(images))))))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts:
            zf.writestr(name, data.encode("utf-8"))
        for i, (_row, png, _w, _h) in enumerate(images):
            zf.writestr("xl/media/image%d.png" % (i + 1), png)
    return buf.getvalue()


def xlsx_report(body):
    """POST /api/xlsx -> (bytes, filename) dari kiriman browser."""
    columns = body.get("columns")
    rows = body.get("rows")
    images = body.get("images") or []
    if not isinstance(columns, list) or not columns or len(columns) > 300 \
            or not all(isinstance(c, str) for c in columns):
        raise ApiError(400, "Daftar kolom tidak valid.")
    if not isinstance(rows, list) or len(rows) > MAX_XLSX_ROWS:
        raise ApiError(400, "Baris data tidak valid (maksimal %d baris)." % MAX_XLSX_ROWS)
    for r in rows:
        if not isinstance(r, list) or len(r) != len(columns):
            raise ApiError(400, "Jumlah kolom tiap baris harus sama dengan judul kolom.")
    if not isinstance(images, list) or len(images) != len(rows):
        raise ApiError(400, "Jumlah gambar harus sama dengan jumlah baris.")
    label = body.get("label") or {}
    mm_w = to_float(label.get("w")) or 0.0
    mm_h = to_float(label.get("h")) or 0.0
    if mm_w <= 0 or mm_h <= 0 or mm_w > 2000 or mm_h > 2000:
        raise ApiError(400, "Ukuran label tidak valid.")

    packed = []
    for index, item in enumerate(images):
        if not item:
            continue
        if not isinstance(item, str):
            raise ApiError(400, "Gambar harus berupa data base64 PNG.")
        raw = item.split(",", 1)[1] if item.startswith("data:") else item
        try:
            png = base64.b64decode(raw, validate=True)
        except (ValueError, binascii.Error):
            raise ApiError(400, "Gambar PNG tidak valid pada baris %d." % (index + 1))
        if not png.startswith(PNG_MAGIC):
            raise ApiError(400, "Gambar bukan PNG pada baris %d." % (index + 1))
        if len(packed) >= MAX_XLSX_IMAGES:
            raise ApiError(400, "Maksimal %d gambar per file Excel." % MAX_XLSX_IMAGES)
        packed.append((index, png, mm_w, mm_h))

    header = ["Label"] + list(columns)
    body_rows = []
    for i, values in enumerate(rows):
        body_rows.append([None] + list(values))
    name = clean_name(body.get("filename") or "label") or "label"
    if not name.lower().endswith(".xlsx"):
        name += ".xlsx"
    return build_xlsx(header, body_rows, packed, (mm_w, mm_h)), name


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

    def send_bytes(self, data, ctype, filename=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition",
                             'attachment; filename="%s"' % filename.replace('"', ""))
        self.end_headers()
        self.wfile.write(data)

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
            if method == "POST" and path.rstrip("/") == "/api/xlsx":
                data, filename = xlsx_report(self.read_json())
                self.send_bytes(data, XLSX_MIME, filename)
                return
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
