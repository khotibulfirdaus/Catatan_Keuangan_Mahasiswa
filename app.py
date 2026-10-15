"""
Backend "Catatan Keuangan Mahasiswa" (Python + Flask + SQLite)

Cara menjalankan:
    pip install -r requirements.txt
    python app.py
Lalu buka http://127.0.0.1:5000 di browser.

Pembagian tugas:
- Frontend (templates/index.html): tampilan + kirim/terima data lewat fetch().
- Backend  (file ini): menyimpan data di database SQLite (keuangan.db),
  mengurus daftar/masuk akun, dan memeriksa semua data yang masuk.
"""
import os
import re
import secrets
import sqlite3
import time
from datetime import date, timedelta
from functools import wraps

from flask import Flask, g, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "keuangan.db")
KEY_PATH = os.path.join(BASE, ".secret_key")


def ambil_secret_key():
    """Kunci rahasia untuk menandatangani cookie login. Dibuat sekali lalu disimpan di file."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    if not os.path.exists(KEY_PATH):
        with open(KEY_PATH, "w") as f:
            f.write(secrets.token_hex(32))
    with open(KEY_PATH) as f:
        return f.read().strip()


app = Flask(__name__)
app.secret_key = ambil_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,       # cookie tidak bisa dibaca JavaScript
    SESSION_COOKIE_SAMESITE="Lax",      # cookie tidak ikut terkirim dari situs lain
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=16 * 1024,       # batasi ukuran permintaan (16 KB)
    TEMPLATES_AUTO_RELOAD=True,
)

# ---------------------------------------------------------------- DATABASE


def db():
    """Satu koneksi database per permintaan."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def tutup_db(_):
    koneksi = g.pop("db", None)
    if koneksi is not None:
        koneksi.close()


def buat_tabel():
    with sqlite3.connect(DB_PATH) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS pengguna (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
                sandi_hash  TEXT NOT NULL,
                dibuat      INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transaksi (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL REFERENCES pengguna(id) ON DELETE CASCADE,
                judul     TEXT NOT NULL,
                nominal   INTEGER NOT NULL,
                kategori  TEXT NOT NULL,
                tanggal   INTEGER NOT NULL,
                bulan     INTEGER NOT NULL,      -- 0 = Januari ... 11 = Desember
                tahun     INTEGER NOT NULL,
                tipe      TEXT NOT NULL CHECK (tipe IN ('pemasukan', 'pengeluaran')),
                dibuat    INTEGER NOT NULL,      -- waktu dicatat (milidetik)
                diubah    INTEGER                -- waktu terakhir diubah (milidetik)
            );
            CREATE INDEX IF NOT EXISTS idx_transaksi_user ON transaksi(user_id);
            """
        )


def sekarang_ms():
    return int(time.time() * 1000)


# ---------------------------------------------------------------- BANTUAN


def wajib_login(fungsi):
    @wraps(fungsi)
    def bungkus(*args, **kwargs):
        if "user_id" not in session:
            return jsonify(pesan="Silakan masuk dulu."), 401
        return fungsi(*args, **kwargs)

    return bungkus


def galat(pesan, kode=400):
    return jsonify(pesan=pesan), kode


def ke_dict(baris):
    d = dict(baris)
    d.pop("user_id", None)
    return d


def bilangan_bulat(nilai):
    """Terima 5 atau 5.0, tolak True/False, teks, dan angka pecahan."""
    if isinstance(nilai, bool):
        return None
    if isinstance(nilai, int):
        return nilai
    if isinstance(nilai, float) and nilai.is_integer():
        return int(nilai)
    return None


def periksa_transaksi(data):
    """Validasi data transaksi dari browser. Mengembalikan (nilai, pesan_error)."""
    if not isinstance(data, dict):
        return None, "Data tidak valid."

    judul = str(data.get("judul", "")).strip()
    if not judul:
        return None, "Judul transaksi belum diisi."
    if len(judul) > 60:
        return None, "Judul maksimal 60 karakter."

    nominal = bilangan_bulat(data.get("nominal"))
    if nominal is None or nominal <= 0:
        return None, "Nominal harus lebih dari 0."
    if nominal > 9_999_999_999_999:
        return None, "Nominal terlalu besar."

    tipe = data.get("tipe")
    if tipe not in ("pemasukan", "pengeluaran"):
        return None, "Tipe harus pemasukan atau pengeluaran."

    kategori = str(data.get("kategori", "")).strip()
    if not kategori or len(kategori) > 40:
        return None, "Kategori tidak valid."

    tanggal = bilangan_bulat(data.get("tanggal"))
    bulan = bilangan_bulat(data.get("bulan"))
    tahun = bilangan_bulat(data.get("tahun"))
    if None in (tanggal, bulan, tahun):
        return None, "Tanggal, bulan, dan tahun harus berupa angka."
    if not 1900 <= tahun <= 2100:
        return None, "Tahun harus antara 1900 dan 2100."
    try:
        date(tahun, bulan + 1, tanggal)  # bulan dari browser mulai dari 0
    except ValueError:
        return None, "Tanggal tersebut tidak ada di kalender."

    return {
        "judul": judul, "nominal": nominal, "tipe": tipe, "kategori": kategori,
        "tanggal": tanggal, "bulan": bulan, "tahun": tahun,
    }, None


# ---------------------------------------------------------------- HALAMAN


@app.route("/")
def beranda():
    return render_template("index.html")


# ---------------------------------------------------------------- AKUN


def masukkan_sesi(user_id):
    session.clear()
    session["user_id"] = user_id
    session.permanent = True


@app.post("/api/daftar")
def daftar():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    sandi = str(data.get("sandi", ""))

    if not re.fullmatch(r"[A-Za-z0-9_.]{3,30}", username):
        return galat("Nama pengguna 3-30 karakter: huruf, angka, titik, atau garis bawah.")
    if not 6 <= len(sandi) <= 128:
        return galat("Kata sandi minimal 6 karakter.")

    try:
        cur = db().execute(
            "INSERT INTO pengguna (username, sandi_hash, dibuat) VALUES (?, ?, ?)",
            (username, generate_password_hash(sandi), sekarang_ms()),
        )
        db().commit()
    except sqlite3.IntegrityError:
        return galat("Nama pengguna sudah dipakai.", 409)

    masukkan_sesi(cur.lastrowid)
    return jsonify(pengguna={"username": username}), 201


@app.post("/api/masuk")
def masuk():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    sandi = str(data.get("sandi", ""))

    baris = db().execute(
        "SELECT id, username, sandi_hash FROM pengguna WHERE username = ?", (username,)
    ).fetchone()
    if baris is None or not check_password_hash(baris["sandi_hash"], sandi):
        return galat("Nama pengguna atau kata sandi salah.", 401)

    masukkan_sesi(baris["id"])
    return jsonify(pengguna={"username": baris["username"]})


@app.post("/api/keluar")
def keluar():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/saya")
@wajib_login
def saya():
    baris = db().execute(
        "SELECT username FROM pengguna WHERE id = ?", (session["user_id"],)
    ).fetchone()
    if baris is None:  # akun sudah tidak ada
        session.clear()
        return galat("Silakan masuk dulu.", 401)
    return jsonify(pengguna={"username": baris["username"]})


# ---------------------------------------------------------------- TRANSAKSI (CRUD)


@app.get("/api/transaksi")  # READ: semua transaksi milik akun ini
@wajib_login
def daftar_transaksi():
    baris = db().execute(
        "SELECT * FROM transaksi WHERE user_id = ? "
        "ORDER BY tahun DESC, bulan DESC, tanggal DESC, id DESC",
        (session["user_id"],),
    ).fetchall()
    return jsonify(transaksi=[ke_dict(b) for b in baris])


@app.post("/api/transaksi")  # CREATE
@wajib_login
def tambah_transaksi():
    nilai, error = periksa_transaksi(request.get_json(silent=True))
    if error:
        return galat(error)

    cur = db().execute(
        "INSERT INTO transaksi (user_id, judul, nominal, kategori, tanggal, bulan, tahun, tipe, dibuat) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session["user_id"], nilai["judul"], nilai["nominal"], nilai["kategori"],
         nilai["tanggal"], nilai["bulan"], nilai["tahun"], nilai["tipe"], sekarang_ms()),
    )
    db().commit()
    baris = db().execute("SELECT * FROM transaksi WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(transaksi=ke_dict(baris)), 201


@app.put("/api/transaksi/<int:tid>")  # UPDATE
@wajib_login
def ubah_transaksi(tid):
    nilai, error = periksa_transaksi(request.get_json(silent=True))
    if error:
        return galat(error)

    cur = db().execute(
        "UPDATE transaksi SET judul=?, nominal=?, kategori=?, tanggal=?, bulan=?, tahun=?, "
        "tipe=?, diubah=? WHERE id=? AND user_id=?",
        (nilai["judul"], nilai["nominal"], nilai["kategori"], nilai["tanggal"], nilai["bulan"],
         nilai["tahun"], nilai["tipe"], sekarang_ms(), tid, session["user_id"]),
    )
    db().commit()
    if cur.rowcount == 0:
        return galat("Transaksi tidak ditemukan (mungkin sudah dihapus).", 404)
    baris = db().execute("SELECT * FROM transaksi WHERE id = ?", (tid,)).fetchone()
    return jsonify(transaksi=ke_dict(baris))


@app.delete("/api/transaksi/<int:tid>")  # DELETE
@wajib_login
def hapus_transaksi(tid):
    cur = db().execute(
        "DELETE FROM transaksi WHERE id = ? AND user_id = ?", (tid, session["user_id"])
    )
    db().commit()
    if cur.rowcount == 0:
        return galat("Transaksi tidak ditemukan (mungkin sudah dihapus).", 404)
    return jsonify(ok=True)


# ---------------------------------------------------------------- PESAN ERROR JSON


@app.errorhandler(404)
def tidak_ada(_):
    if request.path.startswith("/api/"):
        return galat("Alamat API tidak ditemukan.", 404)
    return "Halaman tidak ditemukan.", 404


@app.errorhandler(413)
def terlalu_besar(_):
    return galat("Data yang dikirim terlalu besar.", 413)


buat_tabel()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
