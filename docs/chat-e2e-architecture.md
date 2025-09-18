# Arsitektur End-to-End Chat (REST + WebSocket)

Dokumen ini menjelaskan alur komunikasi lengkap antara Frontend (Next.js) dan Backend (Django + Channels + Celery) dari saat pengguna mengirim pesan hingga pesan balasan diterima dan dirender di halaman chat.

## Komponen Utama

- Backend:
  - Django REST API untuk CRUD percakapan dan pesan
  - Django Channels (WebSocket) untuk notifikasi realtime
  - Celery worker untuk menjalankan task agen/LLM dan mengirim event
- Frontend:
  - Next.js (App Router) + shadcn-ui
  - Komponen UI khusus di `src/components/ai-elements` (Conversation, Message, Tool, PromptInput, dll.)
- Autentikasi:
  - Clerk (JWT) untuk REST dan WebSocket

---

## Alur Tingkat Tinggi

1. Pengguna membuka halaman chat detail `/chat/[conversation_id]` dan halaman memuat riwayat percakapan lewat REST GET.
2. Frontend membuka koneksi WebSocket ke backend pada path khusus percakapan untuk menerima notifikasi realtime.
3. Pengguna mengetik pesan dan menekan kirim (melalui `PromptInput`). Frontend mengirim POST ke REST API untuk membuat pesan baru (opsional: melampirkan gambar dalam base64).
4. Backend menyimpan pesan, memicu proses agen/LLM (via Celery), dan selama proses itu menghasilkan pesan/toolcall baru.
5. Setiap pesan baru/toolcall dikirim ke grup WebSocket percakapan sebagai event notifikasi.
6. Frontend menerima event WS, mem-parsing payload menjadi Message, memperbarui state, dan merendernya di UI menggunakan komponen `ai-elements`.

---

## Backend – Detail Implementasi

### 1) Routing WebSocket
- File: `consumers/router.py`
- Pola URL: `ws/conversations/(?P<conversation_id>[^/]+)/$`
- Mengarah ke consumer: `ConversationConsumer`

### 2) ASGI + Middleware Autentikasi
- File: `config/asgi.py`
- `ProtocolTypeRouter` untuk `websocket` membungkus `URLRouter(websocket_urlpatterns)` dengan `ClerkJWTAuthMiddleware`.
- `ClerkJWTAuthMiddleware` (file: `common/channels_auth.py`) mengambil token dari query string `?token=` atau header `Authorization` dan memverifikasi JWT, lalu menetapkan `scope["user"]`.

### 3) Consumer WebSocket
- File: `app/consumers/agent_consumers.py`
- `ConversationConsumer.connect()`:
  - Membaca `conversation_id` dari URL route param.
  - Menambahkan channel ke group conversation (lihat penamaan di bawah).
- `ConversationConsumer.disconnect()`:
  - Menghapus channel dari grup.
- `ConversationConsumer.notify()`:
  - Menerima event dari channel layer dan mengirim JSON ke client.

### 4) Pengiriman Notifikasi ke Grup
- File: `app/consumers/notifications.py`
- `ws_group_name(conversation_id)` -> `conv_{conversation_id}`
- `send_notification(channel_layer, conversation_id, event, payload)`:
  - `group_send({ type: "notify", event, payload })`
  - Struktur yang dikirim ke client melalui consumer adalah JSON `{ event, payload }`.
- Tersedia juga versi async: `send_notification_async`.

### 5) REST API Relevan
- GET `/v1/chat/conversations/{conversation_id}` – memuat metadata percakapan dan daftar pesan awal.
- POST `/v1/chat/conversations/{conversation_id}/messages` – membuat pesan user baru. Body minimal: `{ content, base64_image? }`.

### 6) Proses Background (Celery)
- Saat pesan user dibuat, backend memicu task Celery untuk menjalankan agen/LLM.
- Ketika agen menghasilkan output (pesan asisten atau toolcall), kode backend memanggil `send_notification(_async)` untuk menyiarkan event ke grup WS `conv_{conversation_id}`.

---

## Frontend – Detail Implementasi

### 1) File Halaman
- File: `frontend/src/app/chat/[conversation_id]/page.tsx`
- Tanggung jawab:
  - Memuat data awal percakapan via REST.
  - Membuka WS dan menangani event masuk.
  - Merender UI chat menggunakan komponen `ai-elements`.
  - Mengirim pesan baru lewat REST ketika pengguna submit prompt.

### 2) Memuat Data Awal (REST)
- Hook: `useRestFetch` dengan `Clerk` `getToken({ template: "manus" })` untuk menyertakan Authorization.
- Endpoint: `GET /v1/chat/conversations/{conversation_id}`
- State yang diset: `conversation`, `messages` (diurutkan ascending berdasarkan `created_at`).

### 3) Koneksi WebSocket
- Hook: `useConversationWS({ conversationId, getToken, onMessage })`
- URL WS (secara logis): `ws/conversations/{conversation_id}/?token=<JWT>`
- Autentikasi: token Clerk dioper ke query string atau header oleh hook implementasi.

### 4) Format Event yang Diterima
- Backend mengirim event ke client dalam bentuk berikut:
  - `{ event: string, payload: Message }` atau
  - `{ event: string, payload: { message: Message } }`
- Frontend menyediakan fungsi parser fleksibel `extractMessageFromWS(data)` yang menormalkan kedua format menjadi `Message`.

Contoh payload (toolcall):
```json
{
  "event": "message.created",
  "payload": {
    "message": {
      "id": "msg_123",
      "conversation_id": "conv_abc",
      "role": "tool",
      "content": "{\"result\": \"ok\"}",
      "tool_call_id": "tc_789",
      "created_at": "2025-01-01T01:23:45Z"
    }
  }
}
```

### 5) Update State dan Dedup
- Callback `onMessage` memanggil `extractMessageFromWS(data)`.
- Jika `message.conversation_id` cocok dan belum ada di state (cek `id`), pesan ditambahkan dan daftar di-sort berdasarkan `created_at`.

### 6) Render UI dengan Komponen `ai-elements`
- Kontainer:
  - `Conversation`, `ConversationContent`, `ConversationScrollButton`
- Pesan user/asisten:
  - `Message` (prop `from` = `"user" | "assistant"`), `MessageAvatar`, `MessageContent`, `Response` (untuk teks)
- Gambar base64:
  - `Image` (prop: `base64`, `uint8Array`, `mediaType`, `alt`)
- Tool-call (role: `"tool"`):
  - `Tool`, `ToolHeader`, `ToolContent`, `ToolOutput`
  - `ToolHeader.type` bertipe literal `tool-${string}`; gunakan identitas tool_call untuk mengisi nilai ini.
- Empty state dan error:
  - `ConversationEmptyState` untuk state kosong; banner sederhana untuk error.

### 7) Input Prompt dan Pengiriman Pesan
- Komponen: `PromptInput`
- `onSubmit(message, event)` menangani:
  - Append optimistik pesan user ke state (contoh di file: `conversation_id: conversationId, role: "user"`)
  - Ambil attachment pertama (jika ada), fetch blob → base64
  - POST ke endpoint: `/v1/chat/conversations/{conversation_id}/messages`
  - Balasan asisten akan masuk melalui WS (tidak menunggu response body untuk konten balasan)

---

## Otentikasi dan Keamanan
- REST: Clerk JWT dikirim di header `Authorization: Bearer <token>`.
- WebSocket: Clerk JWT dilewatkan via query param `token` atau header.
- Backend memverifikasi token via JWKS dan memasang `scope["user"]` sebelum mengizinkan akses WS.

---

## Diagram Alur Sederhana

```
[User] --(PromptInput submit)--> [Next.js]
  |                                 |
  |        REST POST /messages      v
  |-----------------------------> [Django REST]
  |                                 |
  |                           [DB persist]
  |                                 |
  |                         [Celery task start]
  |                                 |
  |<--- WS event (message/tool) -- [Channels group]
  |                                 ^
  |                            send_notification
  v
[Next.js setState + render with ai-elements]
```

---

## Troubleshooting Penting
- Format payload WS bisa berbeda antar sumber (langsung `Message` vs. `payload.message`). Gunakan parser yang fleksibel (seperti `extractMessageFromWS`).
- Pastikan `NEXT_PUBLIC_WS_BASE_URL` (jika digunakan di hook WS) dan konfigurasi domain Clerk benar, agar koneksi WS dan Clerk SDK tidak gagal.
- `ToolHeader.type` harus bertipe `tool-${string}` untuk lolos pengecekan tipe TypeScript.
- Komponen `Image` dari `ai-elements` mengharuskan `uint8Array` (meski tidak digunakan untuk render base64); sediakan nilai dummy (mis. `new Uint8Array(0)`) agar sesuai tipe.

---

## Referensi File Penting
- Backend
  - `consumers/router.py` – URL pattern WS
  - `config/asgi.py` – konfigurasi ASGI + middleware Channels
  - `common/channels_auth.py` – Clerk JWT middleware untuk WS
  - `app/consumers/agent_consumers.py` – WebSocket consumer (connect/disconnect/notify)
  - `app/consumers/notifications.py` – helper `ws_group_name`, `send_notification(_async)`
  - `app/api.py` – endpoint REST untuk percakapan/pesan (dan pemicu Celery)
- Frontend
  - `frontend/src/app/chat/[conversation_id]/page.tsx` – halaman chat, fetch awal, WS, render UI
  - `frontend/src/components/ai-elements/*` – komponen UI chat (Message, Tool, PromptInput, Conversation, Response, Image)

---

## Uji Cepat
1. Buka `/chat/{conversation_id}` (pengguna harus login Clerk).
2. Ketik pesan dan kirim. Lihat bubble user muncul (optimistik).
3. Pastikan WS tersambung; ketika backend mengirim notifikasi, bubble asisten/tool muncul otomatis.
4. Coba lampirkan gambar; pastikan dikirim sebagai base64 dan ditampilkan di UI.