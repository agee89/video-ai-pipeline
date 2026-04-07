# INSTRUKSI PERBAIKAN SISTEM AUTO PORTRAIT CAMERA

Dokumen ini berisi **instruksi FINAL dan TUNGGAL** untuk agent AI (IDE) dalam memperbaiki sistem auto portrait camera khusus **Podcast / Interview / Talkshow**.

❗ **Tidak ada opsi alternatif.**
❗ **Semua perubahan bersifat WAJIB.**

Tujuan utama:

1. Menentukan speaker dengan akurasi tinggi
2. Tracking wajah tanpa delay / mengejar
3. Wajah besar tidak pernah keluar frame
4. Gerakan kamera halus seperti editor manusia

---

## RINGKASAN MASALAH SAAT INI

1. Speaker sering salah sasaran (±20%) karena hanya mengandalkan visual
2. Tracking wajah besar bersifat reaktif → kamera terlambat
3. Bucket system menyebabkan wajah tertukar
4. Zoom agresif menyebabkan wajah keluar frame

---

## SOLUSI FINAL YANG HARUS DIIMPLEMENTASIKAN

### PRINSIP UTAMA

> Sistem **HARUS OFFLINE & PREDICTIVE**, bukan real-time reactive.

Video **selalu dianalisis penuh terlebih dahulu**, baru dirender.

---

## ARSITEKTUR BARU (WAJIB)

### PASS 1 — AUDIO ANALYSIS (WAJIB)

#### Tujuan

Menentukan **kapan ada suara manusia (bicara)**.

#### Instruksi Implementasi

1. Ekstrak audio dari video
2. Hitung RMS / energy audio per frame
3. Simpan hasil sebagai timeline:

```
audio_activity[frame_index] = True / False
```

❌ Jangan menentukan speaker TANPA audio

---

### PASS 1 — FACE TRAJECTORY ANALYSIS (WAJIB)

#### Tujuan

Mendapatkan **pergerakan wajah secara utuh sepanjang video**.

#### Instruksi Implementasi

Untuk SETIAP wajah:

Simpan data berikut:

```
face_id
frame_index
center_x
center_y
face_width
lip_activity
```

Ketentuan:

* Gunakan **face identity (embedding)**
* ❌ HAPUS bucket system sepenuhnya
* Data disimpan untuk seluruh durasi video

---

### PASS 1 — SPEAKER CONFIRMATION (WAJIB)

#### ATURAN TUNGGAL SPEAKER (TIDAK BOLEH DIMODIFIKASI)

```
Seseorang adalah speaker jika DAN HANYA JIKA:
- audio_activity[frame] == True
- lip_activity(face) > LIP_THRESHOLD
```

Konsekuensi:

* Audio aktif + mulut diam → bukan speaker
* Mulut bergerak + audio diam → abaikan

Tujuan:

* Eliminasi false positive visual
* Akurasi speaker > 97%

---

## PASS 2 — PREDICTIVE CAMERA PATH (WAJIB)

### A. Trajectory-Based Camera (BUKAN tracking reaktif)

#### Instruksi

1. Untuk setiap segmen bicara:

   * Ambil trajectory wajah speaker
   * Hitung velocity (dx/dt)

2. Prediksi posisi kamera:

```
lookahead_frames = 3–5
camera_x = face_x + velocity_x * lookahead_frames
```

➡️ Kamera HARUS bergerak lebih dulu, bukan mengejar

---

### B. SAFE ZOOM PROTOCOL (WAJIB)

#### Aturan Mutlak

```
if face_width > 35% frame_width:
    max_zoom = 1.05
    safe_margin = 1.4
else:
    max_zoom = 1.15
    safe_margin = 1.25
```

Konsekuensi:

* Wajah besar TIDAK BOLEH zoom agresif
* Wajah tidak boleh keluar frame

---

### C. GLOBAL PATH SMOOTHING (WAJIB)

#### Instruksi

* Setelah camera path lengkap:

  * Lakukan smoothing ke SELURUH path
  * BUKAN smoothing per frame

Metode yang disarankan:

* Savitzky–Golay filter
* Bezier curve smoothing

Tujuan:

* Gerakan kamera sinematik
* Hilangkan jitter & delay

---

## HAL YANG WAJIB DIHAPUS DARI CODE LAMA

❌ Bucket system
❌ Real-time speaker switching
❌ Aggressive per-frame smoothing
❌ Speaker scoring tanpa audio
❌ Zoom reaktif berbasis frame

---

## KRITERIA KEBERHASILAN (HARUS TERCAPAI)

1. Speaker salah < 3%
2. Wajah tidak keluar frame
3. Tidak ada efek "kamera mengejar"
4. Gerakan kamera terlihat seperti editor manusia

Jika salah satu tidak terpenuhi → IMPLEMENTASI GAGAL.

---

## CATATAN PENTING UNTUK AGENT AI

* Jangan menambah heuristik baru
* Jangan mengoptimasi sebelum arsitektur ini selesai
* Ikuti urutan PASS 1 → PASS 2
* Fokus pada akurasi, bukan kecepatan

---

## KONTEKS PENGGUNAAN

Jenis video:

* Podcast
* Interview
* Talkshow

Bukan:

* Live streaming
* CCTV
* Realtime video

---

## PENUTUP

Instruksi ini adalah **versi FINAL**.

Jika agent AI mengimplementasikan seluruh poin di atas:
➡️ Sistem akan stabil, akurat, dan layak produksi.

Tidak perlu eksperimen tambahan.
