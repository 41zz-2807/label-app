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

## Menyimpan dan membuka desain

Toolbar punya kelompok **Berkas**: kolom nama berkas, tombol **Buka**, dan tombol **Save**
(`Ctrl+S` / `Ctrl+O`, jalan dari mana saja termasuk saat fokus di kolom nama).

- **Save** mengunduh desain ke komputer sebagai `.json` (nama berkas otomatis dibersihkan:
  karakter `/ \ : * ? " < > |` diganti `-`, panjang dibatasi 80 karakter, ekstensi `.json`
  ditambahkan otomatis).
- **Buka** memakai pemilih berkas yang sama dengan memuat data. Berkas `.json` yang dipilih
  dibaca sebagai desain; CSV/Excel tetap dibaca sebagai data.
- Yang disimpan **hanya desain** (kertas, ukuran label, jumlah salinan, dan elemen). Data/baris
  tetap diimpor dari CSV atau Excel, jadi satu desain bisa dipakai untuk banyak data.
- Tombol **Save** dan judul tab bertanda `•` selama ada perubahan yang belum disimpan — selama
  itu, desain baru ada di browser itu saja.

Berkas `.json` dibaca dengan validasi ketat: penanda `app`, nomor versi, jenis elemen, simbol, dan
format barcode harus dikenal; semua angka dijepit ke rentang wajar; maksimal 500 elemen.
Berkas yang bukan desain aplikasi ini, rusak, atau versi lebih baru ditolak **tanpa mengubah
desain yang sedang dikerjakan**.

## Membuat berkas (tombol Generate)

Satu tombol **Generate** di bilah atas; pilih dulu hasil yang diinginkan dari dropdown di
sebelahnya.

| Pilihan | Hasil |
|---|---|
| **PDF label** | PDF seperti biasa, satu label per posisi di lembar stiker. |
| **Excel: gambar label + data** | Satu baris Excel per baris data. Kolom `A` berisi gambar label utuh (barcode, QR, teks, simbol ikut), lalu `#`, `jumlah_cetak`, dan semua kolom data. Gambar berukuran tepat seperti label di layar (mis. 50×30 mm) pada 200 dpi. |
| **Excel: barcode/QR saja** | Satu baris Excel per kode, **hanya barcode/QR-nya tanpa teks dan simbol lain**. Kolom `A` berisi gambar kode itu sendiri (mis. 46×12 mm), lalu `Isi`, `Jenis`, `Elemen`, `Baris`, `Jumlah cetak`. Berguna kalau mau menyusun sheet barcode sendiri di Excel. |

Di panel **Data** ada dua tombol terpisah untuk tabel data saja: **Ekspor Excel** (`.xlsx`,
semua sheet ikut) dan **Ekspor CSV** (`.csv`).

Catatan:

- Semua elemen barcode/QR pada desain ikut diekspor, masing-masing sebagai baris sendiri.
  Barcode kosong atau isinya tidak valid untuk formatnya (mis. EAN13 dengan 5 digit)
  dilewati, dan jumlahnya dilaporkan di baris status.
- Batas 300 gambar per file. Bila data atau kode melebihi batas, aplikasi menawarkan
  mengekspor 300 yang pertama.
- Angka yang polos (`10.50`) ditulis sebagai angka sehingga bisa dijumlahkan di Excel. Teks
  berawalan nol (`007`, `BRG-0001`) dan yang berformat lain (`Rp 85.000`) **tetap teks**, supaya
  kode barang tidak berubah.
- Ibaris Excel yang tidak punya gambar (baris melebihi batas) tetap berisi kolom datanya.
- File `.xlsx` dibuat di server (`POST /api/xlsx`, hanya `zipfile` bawaan Python), gambar
  ditanamkan sebagai gambar asli di dalam sheet — bukan tautan atau teks. Ukuran tiap gambar
  ditulis dalam EMU, jadi barcode tidak teregang walau lebar kolom berubah.
- Yang tertanam adalah hasil render browser, jadi font mengikuti sistem. Judul teks memakai
  pemenggalan baris yang sama dengan pratinjau dan PDF (`textLayout`).

## Elemen di dalam label

| Jenis | Isi |
|---|---|
| Teks | Satu blok teks, bisa `{NamaKolom}`, rata kiri/tengah/kanan, pilihan huruf (Helvetica/Times/Courier), font mengecil sendiri agar muat |
| Barcode | CODE128, CODE39, EAN13, EAN8, UPC, ITF, opsional teks di bawahnya |
| QR | Kode QR (tingkat M), selalu proporsional |
| Kotak/garis | Persegi atau garis lurus (tinggi 0), untuk pembatas |
| Simbol | Panah (→ ← ↑ ↓ ⇄), chevron, garis, segitiga, ketupat, plus, bintang, hati, petir, centang, silang, lingkaran, persegi — dengan pilihan gaya garis / isi / garis+isi dan tebal garis |

Semua elemen bisa digeser dan diperbesar lewat gagang kuning di pojok elemen, atau diisi
 angkanya di panel properti.

**Jenis huruf** (elemen teks): Helvetica (sans-serif), Times (serif), atau Courier
(monospace). Ketiganya adalah font standar PDF, jadi tidak ada file font yang ikut dikirim dan
ukuran PDF tetap kecil. Tumpukan huruf di layar dipilih yang metriknya sama dengan font PDF
(Arial untuk Helvetica, Times New Roman untuk Times, dan seterusnya) supaya pemenggalan baris
tidak meleset antara pratinjau dan hasil cetak. Simbol dan garis digambar sebagai **vektor** (bukan gambar),
jadi tetap tajam di PDF berapa pun ukurannya dan tidak bergantung pada font.

## Login dan pengguna

Aplikasi minta masuk dulu. **Templat, data, riwayat cetak, dan draft desain disimpan terpisah
untuk tiap pengguna** — dua orang bisa memakai nama yang sama tanpa saling menimpa.

- Sesi disimpan di cookie `sid` (`HttpOnly`, `SameSite=Lax`) yang isinya **hash SHA-256** dari
  token acak, jadi bocornya isi tabel `sessions` tidak langsung memberi akses. Berlaku 30 hari
  (ubah dengan `SESSION_DAYS`), lalu otomatis kedaluwarsa.
- Kata sandi disimpan dengan PBKDF2-HMAC-SHA256 150.000 iterasi + salt acak, tidak pernah polos.
- Draft desain di `localStorage` memakai kunci per pengguna (`labelmaker:v1:<nama>`), jadi orang
  berbeda tidak saling menimpa walau satu browser.
- Semua endpoint `/api/*` menolak tanpa sesi (401). Yang terbuka hanya `/api/health`, `/api/me`,
  dan `/api/login`.

### Membuat pengguna

Pengguna pertama dibuat otomatis saat aplikasi pertama jalan. Kalau `ADMIN_USER` + `ADMIN_PASS`
diset di `docker-compose.yml`, itu yang dipakai. Kalau tidak, kata sandi acak dicetak ke log:

```bash
docker compose logs | grep -A3 "Pengguna admin"
```

Setelah itu, menambah atau mengubah pengguna lewat CLI di dalam container:

```bash
docker compose exec label-app python server.py --add-user budi     # asks password twice
docker compose exec label-app python server.py --list-users
docker compose exec label-app python server.py --set-password budi
docker compose exec label-app python server.py --del-user budi     # his data stays
```

Kata sandi minimal 6 karakter, nama pengguna minimal 3 karakter dan harus unik.
`--set-password` sekaligus mengeluarkan semua sesi pengguna tersebut.

## Database SQLite

- File database: `./data/labels.db` (folder `data/` di-mount ke `/app/data` di container,
  jadi data tetap ada walau container dihapus).
- **Backup:** salin file `data/labels.db` (hentikan container dulu agar konsisten, atau
  salin juga file `labels.db-wal` dan `labels.db-shm` bila ada).
- **Restore:** taruh file `labels.db` di folder `data/`, lalu `docker compose restart`.

Tabel:

| Tabel | Isi |
|---|---|
| `users` | Nama pengguna, hash kata sandi, salt, tanda admin |
| `sessions` | Token sesi (disimpan sebagai hash), pengguna, masa berlaku |
| `templates` | Templat label (ukuran kertas, ukuran label, elemen), unik **per pengguna** |
| `datasets` | Data CSV/Excel yang disimpan (kolom + baris), unik **per pengguna** |
| `history` | Riwayat cetak: waktu, templat, data, jumlah label, jumlah halaman |

Menyimpan dengan nama yang sudah ada akan menimpa isi lama (upsert) — **di dalam milik pengguna
yang sedang login**. Riwayat dibatasi 1000 entri terakhir per pengguna.

Templat, data, dan riwayat yang ada sebelum login pertama akan menjadi milik **pengguna pertama**
yang dibuat, jadi tidak hilang.

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
| POST | `/api/xlsx` | Susun file `.xlsx` berisi gambar. Kirim `{filename, image_header, label:{w,h}, columns, rows, images}`; `images` berisi PNG base64 per baris — berupa string (pakai ukuran `label`) atau `{png, w, h}` karena tiap kode bisa berbeda ukuran. Batas 300 gambar, 20.000 baris. Mengembalikan `.xlsx` sebagai unduhan. |

## Catatan keamanan

Aplikasi ini punya **login sendiri** (lihat bagian Login di atas), tapi aplikasi ini tidak
mengakhiri TLS. Jalankan di jaringan internal tepercaya; untuk akses dari internet, taruh di
belakang reverse proxy dengan HTTPS (mis. Nginx/Caddy/Traefik). Set `COOKIE_SECURE=1` kalau
diakses lewat HTTPS agar cookie sesi ikut ditandai `Secure`.

Belum ada perlindungan terhadap brute force: endpoint login tidak membatasi jumlah
percobaan dari satu alamat. Kalau diakses dari internet, batasi lewat reverse proxy.

## Mengubah port

Ubah dua baris di `docker-compose.yml` (`ports` dan `PORT`), mis. `"9000:9000"` dan `PORT: "9000"`.

## Build tanpa internet

Unduh 4 file yang tercantum di `fetch_vendor.py` secara manual ke `static/vendor/` dengan
nama yang sama, lalu build seperti biasa (file yang sudah ada dilewati).

## Struktur proyek

```
Dockerfile
docker-compose.yml
server.py          # server + API SQLite + login/sesi + penulis .xlsx (pustaka standar Python)
fetch_vendor.py    # mengunduh jsPDF, SheetJS, JsBarcode, qrcode-generator
static/index.html  # aplikasi
data/              # database SQLite (labels.db)
```
