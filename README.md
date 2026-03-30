# 🚂 Tiket Kereta Notifier (Python - BookingKAI)

Bot Telegram untuk monitoring ketersediaan tiket kereta api via [booking.kai.id](https://booking.kai.id). Otomatis mengecek ketersediaan tiket secara berkala dan mengirim notifikasi ke Telegram ketika tiket tersedia.

> Rewrite dari versi Go — hanya provider **bookingkai**.

## ✨ Fitur

- 🔍 **Auto-monitoring** — Cek ketersediaan tiket secara berkala dengan interval yang bisa dikonfigurasi
- 🤖 **Telegram Bot** — Kontrol dan monitoring via perintah Telegram
- 🛡️ **Cloudflare Bypass** — Menggunakan `curl_cffi` (undetected curl) dengan TLS fingerprint impersonation
- 🚂 **Multi-kereta** — Monitor banyak kereta sekaligus dalam satu bot
- 🔀 **Wildcard** — Gunakan `name: any` atau `name: "*"` untuk semua kereta di rute tertentu
- 💰 **Filter harga** — Set `max_price` untuk hanya notifikasi tiket di bawah harga tertentu
- ⏸️ **Pause/Resume** — Toggle monitoring per kereta via `/toggle`
- 📊 **Status & History** — Pantau statistik dan riwayat pengecekan
- 🌐 **Proxy Support** — Dukungan SOCKS5/HTTP proxy per provider
- 📡 **Webhook & Polling** — Mode webhook (butuh public URL) atau polling

## 📦 Instalasi

### Prasyarat

- Python 3.10+
- Bot Telegram (buat via [@BotFather](https://t.me/BotFather))

### Setup

```bash
# Clone / masuk ke direktori project
cd Tiket-Kereta-Notifier-Py

# Install dependencies
pip install -r requirements.txt

# Salin dan edit config
cp config.yml.example config.yml
# Edit config.yml — isi bot_token dan chat_id
```

## ⚙️ Konfigurasi

Edit `config.yml`:

```yaml
telegram:
  bot_token: "YOUR_BOT_TOKEN"
  chat_id: "YOUR_CHAT_ID"

webhook:
  enabled: false    # true = webhook mode, false = polling mode
  port: 8080
  url: ""           # Public URL jika webhook enabled

trains:
  - name: BENGAWAN
    origin: LPN
    destination: CKR
    date: "2026-04-05"
    interval: 300         # detik (default 5 menit)
    notes: "@username"    # opsional, ditampilkan di notifikasi
    max_price: 350000     # opsional, filter harga maks (0 = tanpa filter)
    providers:
      - bookingkai

      # Dengan proxy:
      # - name: bookingkai
      #   proxy_url: "socks5://127.0.0.1:40000"
```

### Kode Stasiun

Gunakan kode stasiun KAI, contoh: `PSE` (Senen), `GMR` (Gambir), `YK` (Yogyakarta), `LPN` (Lempuyangan), `CKR` (Cikampek), `BD` (Bandung).

## 🚀 Menjalankan

```bash
python main.py

# Atau dengan config custom:
python main.py --config path/to/config.yml
```

## 🤖 Perintah Telegram

| Perintah | Deskripsi |
|---|---|
| `/help` | Tampilkan bantuan |
| `/list` | Daftar semua kereta yang dimonitor |
| `/list <n>` | Detail kereta #n |
| `/check` | Cek semua kereta sekarang |
| `/check <n>` | Cek kereta #n saja |
| `/all <n>` | Tampilkan semua kereta di rute #n (tanpa filter nama) |
| `/status` | Ringkasan status semua kereta |
| `/status <n>` | Status detail kereta #n |
| `/history <n> [count]` | Riwayat pengecekan kereta #n |
| `/toggle <n>` | Pause/resume monitoring kereta #n |

## 🏗️ Struktur Proyek

```
├── main.py              # Entrypoint
├── config.py            # Config loading & validasi
├── models.py            # Data models (Train, CheckResult, dll)
├── utils.py             # Utilitas (parse_price, format, dll)
├── history.py           # History store (thread-safe)
├── provider.py          # Abstract base class Provider
├── bookingkai/
│   ├── scraper.py       # curl_cffi fetch + HTML parser
│   ├── queue.py         # Serialized request queue
│   └── provider.py      # BookingKAI provider
├── telegram_bot/
│   ├── bot.py           # PTB Application wrapper
│   └── commands.py      # Command handlers
├── config.yml.example   # Contoh konfigurasi
└── requirements.txt     # Dependencies
```

## 📚 Tech Stack

| Komponen | Library |
|---|---|
| HTTP Client | [`curl_cffi`](https://github.com/yifeikong/curl_cffi) — Chrome TLS fingerprint impersonation |
| Telegram Bot | [`python-telegram-bot`](https://github.com/python-telegram-bot/python-telegram-bot) v21+ (async) |
| HTML Parser | [`beautifulsoup4`](https://www.crummy.com/software/BeautifulSoup/) + `lxml` |
| Config | [`PyYAML`](https://pyyaml.org/) |

## 📝 Lisensi

MIT
