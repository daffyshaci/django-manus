# Panduan Setup Google Search Console API

## 1. Persiapan Awal

### Membuat Project di Google Cloud Console
1. Buka [Google Cloud Console](https://console.cloud.google.com/)
2. Buat project baru atau pilih project yang sudah ada
3. Aktifkan Google Search Console API:
   - Pergi ke "APIs & Services" > "Library"
   - Cari "Google Search Console API"
   - Klik "Enable"

### Membuat Service Account
1. Pergi ke "APIs & Services" > "Credentials"
2. Klik "Create Credentials" > "Service Account"
3. Isi nama dan deskripsi
4. Klik "Create and Continue"
5. Berikan role "Viewer" atau buat custom role
6. Klik "Done"

### Download Service Account Key
1. Klik pada service account yang baru dibuat
2. Pergi ke tab "Keys"
3. Klik "Add Key" > "Create new key"
4. Pilih format JSON
5. Download file key dan simpan dengan aman

## 2. Konfigurasi di Google Search Console

### Menambahkan Service Account ke Search Console
1. Buka [Google Search Console](https://search.google.com/search-console/)
2. Pilih property website Anda
3. Klik "Settings" di sidebar kiri
4. Pergi ke "Users and permissions"
5. Klik "Add User"
6. Masukkan email service account (format: nama-account@project-id.iam.gserviceaccount.com)
7. Berikan permission "Full" atau "Restricted" sesuai kebutuhan

## 3. Install Dependencies

```bash
pip install google-api-python-client google-auth pandas
```

## 4. Konfigurasi Kode

Edit file `google_search_console_api.py`:

```python
# Ganti dengan path file service account key Anda
SERVICE_ACCOUNT_FILE = 'path/to/your/service-account-key.json'

# Ganti dengan URL website Anda di Search Console
SITE_URL = 'https://example.com/'  # atau 'sc-domain:example.com' untuk domain properties
```

## 5. Jenis Data yang Tersedia

### Dimensions yang Didukung:
- `query`: Keyword pencarian
- `page`: URL halaman
- `country`: Negara
- `device`: Perangkat (desktop, mobile, tablet)
- `searchAppearance`: Tampilan hasil pencarian
- `date`: Tanggal

### Metrics yang Didukung:
- `clicks`: Jumlah klik
- `impressions`: Jumlah impressions
- `ctr`: Click-through rate
- `position`: Posisi rata-rata

## 6. Contoh Penggunaan

### Analisis Keyword Populer
```python
# Data 30 hari terakhir, dikelompokkan oleh keyword
rows = get_search_analytics(
    service, 
    start_date='2024-08-16', 
    end_date='2024-09-16',
    dimensions=['query']
)
```

### Analisis Performa Halaman
```python
# Data dikelompokkan oleh halaman dan keyword
rows = get_search_analytics(
    service, 
    start_date='2024-08-16', 
    end_date='2024-09-16',
    dimensions=['page', 'query']
)
```

### Analisis Geografis
```python
# Data dikelompokkan oleh negara dan device
rows = get_search_analytics(
    service, 
    start_date='2024-08-16', 
    end_date='2024-09-16',
    dimensions=['country', 'device']
)
```

## 7. Batasan dan Quota

- Maksimal 50.000 rows per hari per search type
- Data tersedia dengan delay 2-3 hari
- Quota harian: 2.000 requests per project

## 8. Tips untuk Identifikasi Keyword Potensial

1. **Keyword dengan Impressions Tinggi tapi CTR Rendah**: Peluang untuk optimasi konten yang sudah ada
2. **Keyword dengan Posisi 11-20**: Hampir masuk halaman pertama - fokus optimasi
3. **Long-tail Keywords**: Keyword spesifik dengan intent pencarian yang jelas
4. **Keyword dengan Tren Naik**: Monitor keyword yang semakin populer
5. **Keyword dengan Competition Rendah**: Peluang untuk konten baru

## 9. Troubleshooting

### Error 403: Permission Denied
- Pastikan service account sudah ditambahkan di Search Console
- Pastikan permission yang diberikan cukup

### Error 400: Invalid Parameter
- Periksa format tanggal (YYYY-MM-DD)
- Pastikan dimensions yang digunakan valid

### Data Tidak Ditemukan
- Pastikan website sudah terverifikasi di Search Console
- Pastikan ada traffic organik yang cukup

## 10. Best Practices

1. **Jadwal Pengambilan Data**: Ambil data harian untuk menghindari quota limit
2. **Penyimpanan Data**: Simpan data historis untuk analisis tren
3. **Monitoring**: Buat alert untuk perubahan performa signifikan
4. **Segmentasi**: Analisis data berdasarkan device, country, dll.

## Resources

- [Google Search Console API Documentation](https://developers.google.com/webmaster-tools/v1/searchanalytics)
- [Google Cloud Console](https://console.cloud.google.com/)
- [Service Accounts Guide](https://cloud.google.com/iam/docs/service-accounts)