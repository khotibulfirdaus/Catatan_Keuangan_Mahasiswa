# Catatan Keuangan Mahasiswa

Frontend: HTML + Tailwind CSS (templates/index.html)
Backend : Python + Flask + SQLite (app.py)

## Cara menjalankan
1. Pastikan Python 3.9+ sudah terpasang.
2. Buka terminal di folder ini, lalu:
       pip install -r requirements.txt
       python app.py
3. Buka http://127.0.0.1:5000 di browser, daftar akun, lalu mulai mencatat.

Data tersimpan di file `keuangan.db` (dibuat otomatis saat app.py pertama kali dijalankan).
Catatan: halaman memuat Tailwind CSS dan font dari internet, jadi perlu koneksi internet.

## Struktur
    app.py               <- backend (API + database)
    templates/index.html <- frontend
    requirements.txt     <- daftar library Python

## API
    POST   /api/daftar          buat akun
    POST   /api/masuk           login
    POST   /api/keluar          logout
    GET    /api/saya            cek siapa yang login
    GET    /api/transaksi       baca semua transaksi
    POST   /api/transaksi       tambah transaksi
    PUT    /api/transaksi/<id>  ubah transaksi
    DELETE /api/transaksi/<id>  hapus transaksi
