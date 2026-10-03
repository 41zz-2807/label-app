#!/usr/bin/env python3
"""Mengunduh pustaka JavaScript ke static/vendor agar aplikasi bisa berjalan offline.

Dijalankan otomatis saat `docker compose build`. File yang sudah ada dilewati,
jadi Anda juga bisa menaruh file-file ini secara manual untuk build tanpa internet.
"""
import sys
import urllib.request
from pathlib import Path

CDN = "https://cdnjs.cloudflare.com/ajax/libs/"
FILES = {
    "jspdf.umd.min.js": CDN + "jspdf/2.5.1/jspdf.umd.min.js",
    "xlsx.full.min.js": CDN + "xlsx/0.18.5/xlsx.full.min.js",
    "JsBarcode.all.min.js": CDN + "jsbarcode/3.11.6/JsBarcode.all.min.js",
    "qrcode.min.js": CDN + "qrcode-generator/1.4.4/qrcode.min.js",
}

dest = Path(__file__).resolve().parent / "static" / "vendor"
dest.mkdir(parents=True, exist_ok=True)

failed = False
for name, url in FILES.items():
    target = dest / name
    if target.exists() and target.stat().st_size > 10_000:
        print("ada   ", name)
        continue
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "label-app-build"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if len(data) < 10_000:
            raise ValueError("ukuran file terlalu kecil (%d byte)" % len(data))
        target.write_bytes(data)
        print("unduh ", name, len(data), "byte")
    except Exception as e:  # noqa: BLE001
        failed = True
        print("GAGAL ", name, "-", e, file=sys.stderr)

if failed:
    sys.exit("Gagal mengunduh pustaka. Periksa koneksi internet, atau taruh file secara manual di static/vendor/.")
