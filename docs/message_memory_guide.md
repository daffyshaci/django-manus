# Panduan Message & Memory pada Agent

Dokumen ini menjelaskan dua lapisan data yang digunakan sistem:

1) Skema (in-memory) untuk LLM/agent: didefinisikan di <mcfile name="schema.py" path="c:\Users\DINI\Documents\project\OpenManus\app\schema.py"></mcfile> (Pydantic). Digunakan selama eksekusi agent, tidak langsung berhubungan dengan database.
2) Model (persisten) untuk database: didefinisikan di <mcfile name="models.py" path="c:\Users\DINI\Documents\project\OpenManus\app\models.py"></mcfile> (Django ORM). Dipakai ketika ingin menyimpan riwayat percakapan ke DB serta menyiarkan event WebSocket ke frontend.

Referensi agent dasar: <mcfile name="base.py" path="c:\Users\DINI\Documents\project\OpenManus\app\agent\base.py"></mcfile>

---

## 1. Skema (In-memory) — app/schema.py

### Message (Pydantic)
Field utama:
- role: salah satu dari [system, user, assistant, tool]
- content: teks opsional
- tool_calls: daftar panggilan fungsi/tool (opsional)
- name, tool_call_id: metadata untuk role "tool"
- base64_image: dukungan konten gambar (opsional)

Helper constructor:
- Message.user_message(content, base64_image=None)
- Message.system_message(content)
- Message.assistant_message(content=None, base64_image=None)
- Message.tool_message(content, name, tool_call_id, base64_image=None)
- Message.from_tool_calls(tool_calls, content="", base64_image=None)

### Memory (Pydantic)
- messages: list[Message], default []
- max_messages: int, default 100
- add_message(msg), add_messages(msgs), clear(), get_recent_messages(n), to_dict_list()

Catatan: Memory di skema adalah penampung in-memory untuk loop agent (tidak otomatis tersimpan ke DB).

---

## 2. Model (Persisten) — app/models.py

### Conversation (Django)
- pkid: BigAutoField (primary key numerik)
- id: UUIDField (unik, bukan primary key)
- user, title, llm_model

### Message (Django)
- conversation: ForeignKey ke Conversation
- role, content, tool_calls(JSON), tool_call_id, name, base64_image
- Helper classmethod: user_message(), system_message(), assistant_message(), tool_message(), from_tool_calls()
- to_dict(): normalisasi ke bentuk dict siap konsumsi UI/LLM

### Memory (Django)
- conversation: ForeignKey ke Conversation
- messages: JSONField (list of dict), max_messages
- add_message(): menambah 1 pesan dalam bentuk dict dan menyimpan

Catatan: Model Django di atas merupakan representasi persisten yang tersimpan di DB.

---

## 3. Menambah Pesan ke Loop Agent

Gunakan API agent berikut (lihat BaseAgent di app/agent/base.py):

- update_memory(role, content, base64_image=None, persist=True, **kwargs)
  - Menambah pesan ke Memory (in-memory) terlebih dahulu.
  - Jika persist=True dan sudah ada hook persistensi (lihat bagian 4), maka pesan juga akan disimpan ke DB dan event WebSocket akan dikirim ke frontend.
  - kwargs yang umum:
    - tool_calls: untuk assistant yang membawa panggilan tool (akan memakai Message.from_tool_calls)
    - name, tool_call_id: untuk role="tool"

Contoh pola umum di dalam step agent:

```python
# Tambah pesan user (persist)
self.update_memory("user", "Halo, bantu saya...")

# Tambah pesan assistant tanpa persist (ephemeral)
self.update_memory("assistant", "Catatan internal...", persist=False)

# Tambah pesan assistant dengan tool_calls (persist)
self.update_memory(
    "assistant",
    content="",  # konten bisa kosong bila hanya tool_calls
    tool_calls=[...],
)

# Tambah pesan tool (persist) dengan metadata
self.update_memory(
    "tool",
    content="Hasil eksekusi",
    name="browser",
    tool_call_id="call_123",
)
```

Tips:
- Untuk menambah pesan yang sama sekali tidak memicu persistensi, Anda juga bisa langsung memanggil agent.memory.add_message(Message...) — ini hanya memodifikasi in-memory dan tidak melewati hook persistensi.

---

## 4. Persistensi: Mengaktifkan, Perilaku, dan Batasan

Agar update_memory dapat menulis ke DB, Anda perlu mengaktifkan hook persistensi sekali di awal:

```python
agent.attach_django_persistence(conversation_id)
```

- conversation_id yang dipakai adalah UUID (field Conversation.id), bukan pkid. Pastikan Anda mengoper nilai UUID string. Di sisi hook, lookup menggunakan `Conversation.objects.get(id=...)`.
- Setelah hook aktif, setiap update_memory(..., persist=True) akan:
  1) Menciptakan Message (Django) yang sesuai (user/system/assistant/tool). Jika tool_calls diberikan dan role=assistant, akan memakai Message.from_tool_calls.
  2) Melakukan upsert Memory (Django) untuk conversation terkait, kemudian menambahkan representasi dict pesan tersebut ke messages (JSONField) dengan menjaga max_messages.
  3) Mengirim event WebSocket `message.created` ke grup percakapan, sehingga UI dapat menambahkan pesan baru secara real-time.

Batasan dan catatan penting:
- Jika persist=False, hanya in-memory yang berubah; DB tidak disentuh dan tidak ada event WebSocket.
- Jika persist_message_hook belum di-set (attach_django_persistence belum dipanggil), maka tidak ada persistensi ke DB meskipun persist=True.
- Jika terjadi error selama persistensi, loop agent tetap jalan; error akan dicatat di log dan tidak menggugurkan in-memory memory.

---

## 5. Fungsi yang Tidak Menambah Persistensi

- update_memory(..., persist=False) — selalu hanya menambah ke in-memory.
- Penambahan langsung ke agent.memory, misal `agent.memory.add_message(...)` — tidak memanggil hook persistensi.
- Operasi internal yang tidak memanggil update_memory (misal log internal, perhitungan, dsb.) — tidak mempengaruhi DB.

---

## 6. Praktik Terbaik

- Aktifkan persistensi sedini mungkin dalam alur eksekusi agent yang memang perlu menulis ke DB:
  ```python
  agent.attach_django_persistence(conversation_id=str(conversation.id))
  ```
- Gunakan persist=False untuk pesan ephemeral (catatan internal, prompt antara, dsb.) agar UI/DB tetap bersih.
- Untuk pesan assistant dengan tool_calls, selalu kirim melalui update_memory(role="assistant", tool_calls=...); ini memastikan format tool_calls seragam dan tersimpan dengan benar.
- Periksa tipe ID yang Anda oper. Gunakan UUID (Conversation.id), bukan pkid (integer). Mengoper pk ke UUID field atau sebaliknya akan menimbulkan error tipe.

---

## 7. Pemetaan Singkat

- In-memory (Pydantic) Message -> Saat persist, diproyeksikan menjadi Django Message dan dict-nya ditambahkan ke Django Memory.messages (JSONField).
- In-memory Memory (list[Message]) -> Tidak otomatis sinkron ke DB; sinkronisasi hanya terjadi melalui hook persistensi ketika update_memory dipanggil dengan persist=True.

---

## 8. FAQ Singkat

- Q: Mengapa pesan saya tidak muncul di UI?
  - A: Pastikan `attach_django_persistence()` sudah dipanggil, `persist=True`, dan tidak ada error pada log. UI mengandalkan event `message.created` yang dipancarkan saat persistensi sukses.

- Q: Bagaimana menyimpan pesan pertama secara otomatis?
  - A: Buat Conversation, panggil `attach_django_persistence(conversation.id)`, lalu `update_memory("user", "...")` atau gunakan endpoint yang memang memicu penulisan awal.

- Q: Bagaimana menambah gambar? 
  - A: Sertakan `base64_image` pada `update_memory(...)` atau constructor message yang relevan.