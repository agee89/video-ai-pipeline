# Face Tracking System - Dokumentasi Lengkap

Sistem face tracking untuk reframing video portrait secara otomatis dengan fokus pada speaker aktif.

---

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      VIDEO INPUT (Landscape)                     │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       INITIAL SCAN (~1 detik)                    │
│   • Scan semua wajah                                             │
│   • Hitung GERAKAN setiap wajah                                  │
│   • Lock ke wajah PALING AKTIF (bukan terbesar)                  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FRAME-BY-FRAME PROCESSING                     │
│   Detection → Activity Scoring → Switch Decision → Crop         │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      VIDEO OUTPUT (Portrait 9:16)                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 1. Hybrid Face Detection

Sistem menggunakan dua detector yang bekerja bersamaan:

| Detector | Library | Fungsi | Kelebihan |
|----------|---------|--------|-----------|
| **Face Detection** | MediaPipe | Mendeteksi lokasi wajah | Bekerja di jarak jauh, full body shots |
| **Face Mesh** | MediaPipe | Tracking 468 landmark wajah | Detail lip tracking untuk aktivitas bicara |

### Konfigurasi:
```python
face_detector = mp_face_detection.FaceDetection(
    model_selection=1,              # 0=dekat, 1=jauh (full range)
    min_detection_confidence=0.4    # Confidence threshold
)

face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=6,
    min_detection_confidence=0.4,
    min_tracking_confidence=0.4
)
```

---

## 2. Bucket System

Video dibagi menjadi 12 bucket horizontal untuk tracking posisi wajah:

```
│ 0 │ 1 │ 2 │ 3 │ 4 │ 5 │ 6 │ 7 │ 8 │ 9 │10 │11 │
├───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┤
│              1920px (contoh)                   │
```

Setiap wajah di-assign ke bucket berdasarkan posisi X center-nya.

---

## 3. Activity Scoring

### Komponen Activity:

```python
# Lip Activity (dari Face Mesh)
lip_open = jarak_bibir_atas_ke_bawah  # dalam pixel

# Movement (pergerakan fisik)
movement = abs(x_sekarang - x_sebelumnya) / 10

# Combined Activity
current_activity = face_activity + (lip_activity * 2) + movement
```

### Bobot Scoring untuk Best Face:

```python
activity_score = activity * 1.5 + lip_activity * 2.5 + movement * 1.0
size_score = face_size / size_divisor  # Divisor berubah berdasarkan jumlah wajah

score = activity_score + size_score
```

| Jumlah Wajah | Size Divisor | Efek |
|--------------|--------------|------|
| 1 orang | 150,000 | Size cukup berpengaruh |
| 2 orang | 300,000 | Size kurang berpengaruh |
| 3+ orang | 500,000 | Size hampir tidak berpengaruh |

---

## 4. Sustained Activity

Mencegah switch karena gerakan singkat:

```python
# Jika aktif, tambah counter
if current_activity > 2.0:
    face_sustained_activity[bucket] += 1
else:
    face_sustained_activity[bucket] -= 2  # Reset lebih cepat
```

### Sustained Time berdasarkan Sensitivity:

| Sensitivity | Sustained Required |
|-------------|-------------------|
| 1 | 3.0 detik |
| 5 | 1.9 detik |
| 10 | 0.5 detik |

---

## 5. Switching Conditions

### Mode Normal (< 7 sensitivity atau > 2 orang):

```python
can_switch = (
    cooldown_ok AND
    (NOT locked_on_active OR current_activity < 0.3)
)

other_ready_to_switch = (
    most_active_face exists AND
    different bucket AND
    sustained >= required AND
    activity > 3.0
)
```

### Mode 2-Person Dialog (≥ 7 sensitivity + 2 orang):

```python
instant_dialog_switch = (
    can_instant_switch AND  # Min 2.5 detik sejak switch terakhir
    other_bucket != current_bucket AND
    highest_activity > current_activity * 2.0 AND
    highest_activity > 3.0
)
```

---

## 6. Lock Mode

Saat fokus pada speaker aktif:

```python
# Lock aktif jika activity tinggi
if current_activity > 2.0:
    is_locked_on_active = True
elif current_activity < 0.3:
    is_locked_on_active = False
```

### Efek Lock Mode:
- ✅ Auto zoom proporsional dengan activity
- ✅ Posisi sangat stabil (hanya 5% drift)
- ✅ Tidak mudah switch ke wajah lain
- ✅ Hanya switch jika current benar-benar diam

---

## 7. Lost Face Recovery

Jika wajah target hilang (scene change, keluar frame):

```python
if frames_since_face_seen >= 15:  # ~0.5 detik
    # Switch ke wajah yang terlihat
    tracked_face_x = largest_visible_face['x']
    # Reset zoom
    target_zoom = 1.0
    # Log recovery
    logger.info("RECOVERY: Lost face, switching...")
```

---

## 8. Dynamic Zoom

### Trigger Zoom:

| Kondisi | Target Zoom |
|---------|-------------|
| Mouth very open (≥22px) | 1.25 (max) |
| Mouth moderately open (≥15px) | Proporsional |
| Locked on active speaker | 1.0 + (activity * 0.02) |
| Switch to new speaker | 1.25 (max) |
| Lost face / Recovery | 1.0 (reset) |

### Smoothing:
```python
current_zoom += 0.08 * (target_zoom - current_zoom)
```

---

## 9. Position Smoothing

### Camera Movement:
```python
# Parameter dari API (default 0.25)
smooth_crop_x += camera_smoothing * (target_crop_x - smooth_crop_x)
```

| camera_smoothing | Efek |
|------------------|------|
| 0.05 | Sangat smooth, lambat |
| 0.15 | Smooth |
| 0.25 | Default, balanced |
| 0.35 | Responsif |
| 0.50 | Sangat cepat |

### Position Drift (saat tracking sama orang):
```python
tracked_face_x = 0.95 * tracked_face_x + 0.05 * detected_x
# Hanya 5% perubahan per frame = sangat stabil
```

---

## 10. Parameters Summary

### API Parameters:

| Parameter | Default | Range | Fungsi |
|-----------|---------|-------|--------|
| `tracking_sensitivity` | 5 | 1-10 | Kecepatan switch antar speaker |
| `camera_smoothing` | 0.25 | 0.05-0.5 | Kecepatan pergerakan kamera |

### Internal Constants:

| Constant | Value | Fungsi |
|----------|-------|--------|
| `NUM_BUCKETS` | 12 | Resolusi tracking horizontal |
| `max_zoom` | 1.25 | Maximum zoom (25%) |
| `min_stay_frames` | 2.5s | Minimum stay setelah switch |
| `max_frames_without_face` | 15 | Threshold untuk recovery |
| `lock_activity_threshold` | 2.0 | Threshold untuk lock mode |

---

## 11. Log Messages

| Log | Arti |
|-----|------|
| `Initial lock: bucket=X` | Lock awal ke wajah di bucket X |
| `INSTANT: A -> B` | Switch cepat (2-person dialog) |
| `SWITCH: A -> B` | Switch normal dengan sustained activity |
| `RECOVERY: Lost face` | Wajah hilang, switch ke yang terlihat |
| `Frame X/Y, x=Z, zoom=W` | Status per 300 frame |

---

## 12. Best Practices

### Untuk Interview/Podcast (1-2 orang):
```json
{
  "tracking_sensitivity": 7,
  "camera_smoothing": 0.25
}
```

### Untuk Talk Show (3+ orang):
```json
{
  "tracking_sensitivity": 5,
  "camera_smoothing": 0.20
}
```

### Untuk Single Speaker:
```json
{
  "tracking_sensitivity": 3,
  "camera_smoothing": 0.15
}
```
