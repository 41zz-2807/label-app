# AGENTS.md

Catatan untuk asisten AI (atau manusia) yang mengerjakan repo ini.

## Repository

- Asal (origin): `git@github.com:41zz-2807/label-app.git`
- Repo ini **public**, jadi clone tidak butuh kredensial apa pun. Gunakan HTTPS:

  ```bash
  git clone https://github.com/41zz-2807/label-app.git
  ```

- **Jangan pakai** `git clone git@github.com:...` di host/container yang belum punya SSH
  key GitHub. Gejalanya:

  ```
  git@github.com: Permission denied (publickey).
  fatal: Could not read from remote repository.
  ```

  Repo publik tidak butuh key, jadi error itu murni masalah jalur SSH — pakai HTTPS saja
  sudah cukup.

### Kalau memang butuh SSH (mis. untuk push)

```bash
ssh-keygen -t ed25519 -C "host-container"
cat ~/.ssh/id_ed25519.pub          # tempel di GitHub → Settings → SSH keys
ssh -T git@github.com              # harus muncul: Hi <username>!
```

Alternatif read-only khusus repo ini (deploy key):

```bash
ssh-keygen -t ed25519 -C label-app-deploy -f ~/.ssh/id_ed25519_deploy
ssh-keygen -y -f ~/.ssh/id_ed25519_deploy > /tmp/deploy.pub   # tempel di Settings → Deploy keys
printf 'Host github.com\n  IdentityFile ~/.ssh/id_ed25519_deploy\n  IdentitiesOnly yes\n' >> ~/.ssh/config
```

## Menjalankan

```bash
docker compose up -d --build      # http://localhost:8010
docker compose logs -f
docker compose down
docker compose up -d --build      # bangun ulang setelah mengubah kode
```

- Tidak ada `pip install` dan tidak ada test runner. `server.py` hanya memakai pustaka
  standar Python (`http.server` + `sqlite3` + `zipfile`). Host bisa saja masih Python 3.6,
  jadi uji selalu lewat container `python:3.12-slim` (atau `docker build`), bukan `python3`
  langsung — `ThreadingHTTPServer` baru ada sejak 3.7.
- Build pertama mengunduh 4 pustaka JS ke `static/vendor/` (`fetch_vendor.py`) jadi butuh
  internet; sesudahnya aplikasi offline penuh. Untuk build tanpa internet, taruh file
  tersebut manual dengan nama sama. SheetJS sudah ada, jadi ekspor/ekspor-impor `.xlsx`
  tidak menambah dependensi.
- `static/index.html` berisi seluruh UI **dan** logika dalam satu IIFE, tanpa framework.
- Kalau diuji dengan container terpisah, jangan pakai `docker compose up` pada host yang
  sedang melayani user: jalankan container uji di port lain (mis. 8099) supaya sesi yang
  sedang aktif tidak terputus. Instance yang berjalan hanya kena dampak setelah di-build
  ulang dan di-deploy.

## Yang perlu dijaga saat mengubah kode

- **Simbol & garis adalah vektor, bukan font.** Geometrinya didefinisikan sekali di
  `SYMBOLS` (skema 0..100), lalu dirender tiga kali dari `symGeom()`: SVG untuk pratinjau
  (`symbolSVG`), `doc.lines()` jsPDF untuk PDF (`drawSymbolPDF`), dan `<path>` di
  `labelSVG` untuk ekspor Excel. Ubah semuanya lewat fungsi yang sama supaya pratinjau,
  PDF, dan hasil ekspor tidak berbeda.
- Subpath **tertutup** (lingkaran, persegi) wajib memakai helper `O()`. Polyline terbuka
  membuat sisi terakhir hilang di preview maupun PDF.
- Font PDF adalah Helvetica → karakter non-Latin (CJK, emoji) belum didukung.
- Batas yang perlu dijaga: 20.000 label per PDF, 200.000 baris dataset, 300 gambar per
  file Excel, 20.000 baris per file Excel, body request 64 MB.
- Pratinjau, PDF, **dan ekspor Excel** harus selalu memakai perhitungan teks yang sama
  (`textLayout`), kalau tidak baris akan meleset antara layar dan hasil cetak.
- `elementSVG()` dipakai bersama oleh `labelSVG()` (gambar label utuh) dan `codeSVG()`
  (barcode/QR saja) — jangan menggambar ulang di tempat lain.
- `POST /api/xlsx` mengembalikan biner, jadi tidak boleh lewat `send_json()` yang biasa;
  jalur JSON di `api()` tidak boleh ikut mengubahnya.
- Ukuran gambar di `.xlsx` ditulis dalam EMU (`EMU_PER_MM`), bukan lewat ukuran sel, supaya
  barcode tidak teregang. `row_heights` memakai tinggi gambar milik baris itu sendiri —
  boleh berbeda antar baris pada mode barcode/QR.
- Nilai yang dikirim ke Excel: `cellValue()` hanya mengubah teks polos jadi angka, kode
  ber-nol di depan (`007`) wajib tetap teks. Jangan-longgarkan regexnya.
- `server.py` tidak boleh punya dependensi baru; penulis `.xlsx` memakai `zipfile` dan
  XML tangan. Validasi paket: part wajib ada, semua `.xml`/`.rels` harus bisa di-parse, dan
  hasilnya harus bisa dibaca `openpyxl` (perlu `pillow`) serta SheetJS.

## Data & keamanan

- Database: `data/labels.db`, di-mount ke `/app/data` sehingga tetap ada walau container
  dihapus. **Tidak ikut ter-commit** (lihat `.gitignore`).
- Aplikasi **tidak punya login**. Hanya untuk jaringan internal; untuk akses internet
  pasang reverse proxy dengan autentikasi.
- Backup: hentikan container dulu, lalu salin `data/labels.db` (beserta `labels.db-wal`
  dan `labels.db-shm` bila ada).
