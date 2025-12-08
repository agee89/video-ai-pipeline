# Custom Fonts

Letakkan file font (.ttf) di folder ini.
Font akan otomatis terinstall saat docker build.

---

## Cara Pakai

### 1. Copy File Font
```bash
cp TheBoldFont.ttf video-worker/fonts/
```

### 2. Rebuild Docker
```bash
docker-compose up -d --build video-worker
```

### 3. Cek Nama Font yang Terinstall
```bash
docker exec video_worker fc-list | grep -i "nama-font"
```

Contoh output:
```
/usr/share/fonts/truetype/TheBoldFont.ttf: The Bold Font:style=Regular
```

### 4. Gunakan Nama Font di API
Gunakan nama **sebelum** `:style=`

```json
{
  "settings": {
    "font_family": "The Bold Font"
  }
}
```

---

## Penting!

⚠️ **Nama font di API BUKAN nama file, tapi nama internal font.**

| File | Nama API (salah) | Nama API (benar) |
|------|------------------|------------------|
| `TheBoldFont.ttf` | ❌ `TheBoldFont` | ✅ `The Bold Font` |
| `Montserrat-Bold.ttf` | ❌ `Montserrat-Bold` | ✅ `Montserrat` |
| `Poppins-ExtraBold.ttf` | ❌ `Poppins-ExtraBold` | ✅ `Poppins` |

---

## Cara Cek Nama Font dari File (Mac/Linux)

Sebelum upload ke Docker:
```bash
fc-scan TheBoldFont.ttf | grep family
```

Output:
```
family: "The Bold Font"(s)
```

---

## Font yang Sudah Terinstall

- **Montserrat** (default)
- Liberation Sans, Serif, Mono
