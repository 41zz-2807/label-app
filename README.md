# Aplikasi Cetak Label

Rancang label, muat data dari CSV/Excel, lalu simpan sebagai PDF. Templat, data, dan
riwayat cetak disimpan di database SQLite di dalam proyek ini.

## Menjalankan

```bash
docker compose up -d --build
```

Buka **http://localhost:8010**. Build pertama membutuhkan internet untuk mengunduh
4 pustaka JavaScript ke `static/vendor/`. Setelah itu aplikasi berjalan sepenuhnya offline.

Perintah berguna:

```bash
docker compose logs -f        # lihat log
docker compose down           # hentikan
docker compose up -d --build  # bangun ulang setelah mengubah kode
```

## Elemen di dalam label

| Jenis | Isi |
|---|---|
| Teks | Satu blok teks, bisa `{NamaKolom}`, rata kiri/tengah/kanan, font mengecil sendiri agar muat |
| Barcode | CODE128, CODE39, EAN13, EAN8, UPC, ITF, opsional teks di bawahnya |
| QR | Kode QR (tingkat M), selalu proporsional |
| Kotak/garis | Persegi atau garis lurus (tinggi 0), untuk pembatas |
| Simbol | Panah (→ ← ↑ ↓ ⇄), chevron, garis, segitiga, ketupat, plus, bintang, hati, petir, centang, silang, lingkaran, persegi — dengan pilihan gaya garis / isi / garis+isi dan tebal garis |

Semua elemen bisa digeser dan diperbesar lewat gagang kuning di pojok elemen, atau diisi
 angkanya di panel properti. Simbol dan garis digambar sebagai **vektor** (bukan gambar),
jadi tetap tajam di PDF berapa pun ukurannya dan tidak bergantung pada font.

## Database SQLite

- File database: `./data/labels.db` (folder `data/` di-mount ke `/app/data` di container,
  jadi data tetap ada walau container dihapus).
- **Backup:** salin file `data/labels.db` (hentikan container dulu agar konsisten, atau
  salin juga file `labels.db-wal` dan `labels.db-shm` bila ada).
- **Restore:** taruh file `labels.db` di folder `data/`, lalu `docker compose restart`.

Tabel:

| Tabel | Isi |
|---|---|
| `templates` | Templat label (ukuran kertas, ukuran label, elemen), nama unik |
| `datasets` | Data CSV/Excel yang disimpan (kolom + baris), nama unik |
| `history` | Riwayat cetak: waktu, templat, data, jumlah label, jumlah halaman |

Menyimpan dengan nama yang sudah ada akan menimpa isi lama (upsert).
Riwayat dibatasi 1000 entri terakhir.

## Fitur di panel "Tersimpan di database"

- **Templat label:** simpan desain saat ini dengan nama, muat kembali, atau hapus.
- **Data:** simpan data yang sedang dimuat agar tidak perlu upload ulang.
- **Riwayat cetak:** setiap kali membuat PDF, tercatat otomatis.

## API (opsional, untuk integrasi)

| Method | Path | Keterangan |
|---|---|---|
| GET | `/api/health` | Cek status |
| GET / POST | `/api/templates` | Daftar / simpan `{name, data}` |
| GET / DELETE | `/api/templates/<id>` | Ambil / hapus |
| GET / POST | `/api/datasets` | Daftar / simpan `{name, columns, rows}` |
| GET / DELETE | `/api/datasets/<id>` | Ambil / hapus |
| GET / POST / DELETE | `/api/history` | Daftar / tambah / hapus semua |

## Catatan keamanan

Aplikasi ini **tidak memiliki login**. Jalankan di jaringan internal tepercaya. Untuk akses
dari internet, taruh di belakang reverse proxy dengan autentikasi (mis. Nginx/Caddy/Traefik
dengan basic auth).

## Mengubah port

Ubah dua baris di `docker-compose.yml` (`ports` dan `PORT`), mis. `"9000:9000"` dan `PORT: "9000"`.

## Build tanpa internet

Unduh 4 file yang tercantum di `fetch_vendor.py` secara manual ke `static/vendor/` dengan
nama yang sama, lalu build seperti biasa (file yang sudah ada dilewati).

## Struktur proyek

```
Dockerfile
docker-compose.yml
server.py          # server + API SQLite (hanya pustaka standar Python)
fetch_vendor.py    # mengunduh jsPDF, SheetJS, JsBarcode, qrcode-generator
static/index.html  # aplikasi
data/              # database SQLite (labels.db)
```
