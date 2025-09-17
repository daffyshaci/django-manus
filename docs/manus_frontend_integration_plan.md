# Rencana Integrasi Manus yang Lebih Interaktif dengan Frontend

Tujuan:
- Menyediakan pemilihan agent dari frontend (Manus vs Data Analysis/Visualization).
- Mengizinkan override model LLM saat create agent atau saat run (dipilih dari frontend), dengan fallback ke config default.
- Mendukung input multimodal (text + image) end-to-end tanpa merusak alur yang sudah berjalan.
- Perubahan minimal, tetap backward compatible.

## Ringkasan Kondisi Saat Ini
- Agent umum yang dipakai UI: Manus, dijalankan via Celery task untuk percakapan chat. Entry point: `run_manus_agent(...)` yang memanggil `Manus.create(**kwargs)` lalu `agent.run(...)`. Lihat: app/tasks.py.
- Inisialisasi LLM ada di BaseAgent: jika tidak disuplai, agent membuat `LLM(config_name=self.name.lower())` sesuai nama agent, membaca config.llm. Lihat: app/agent/base.py dan app/llm.py.
- Dukungan gambar (base64): sudah tersedia di schema/model (field `base64_image`), frontend menampilkan gambar, dan LLM memformat `base64_image` ke `image_url` saat model mendukung vision. Lihat: app/schema.py, app/models.py, templates/chat_detail.html, app/llm.py (format_messages, MULTIMODAL_MODELS).
- Data Visualization: tool chain sudah berjalan via DataAnalysis agent (memiliki VisualizationPrepare + DataVisualization) atau bisa dipanggil langsung. Manus belum memuat DataVisualization secara default.

## Desain Arsitektur Baru
1) Pemilihan Agent di Frontend
- Tambahkan selector di UI: mode "General (Manus)" vs "Data Analysis" (yang akan menggunakan DataVisualization melalui DataAnalysis agent).
- Simpan pilihan ini pada pembuatan Conversation, misalnya field `agent_type`.
- Back-end memetakan `agent_type` ke agent yang akan dibuat/dijalankan (Manus atau DataAnalysis).

2) Override Model LLM dari Frontend
- Frontend mengirim pilihan model (misalnya `llm_model`, opsional juga `temperature`, `max_tokens`, dsb.) saat membuat Conversation atau saat trigger run.
- Prioritas (fallback chain):
  - Override per-run (jika dikirim bersama trigger) >
  - Setting pada Conversation (diset saat create) >
  - Default dari config.llm (tidak berubah bila tidak ada override).
- Minimal-change di backend:
  - Tambahkan field opsional di agent untuk menampung `llm_overrides` (dict). Di `initialize_agent`, jika ada overrides, buat `LLM(config_name=unique_key, llm_config=overrides_tergabung)`. Untuk menghindari cache berbasis `config_name`, gunakan `config_name` unik per conversation ketika ada override, mis. `f"{self.name.lower()}:{conversation_id or 'session'}"`.
  - Simpan `llm_model` yang dipilih ke Conversation agar tampil di UI (sudah ada tampilan model saat ini di chat_detail.html).

3) Dukungan Input Gambar (Text + Image)
- Frontend: sediakan input untuk upload/drag-drop gambar. Konversi ke base64 di client (PNG/JPEG) dan kirim bersama payload `content` pada endpoint pesan: `{ content, base64_image }`.
- Backend: endpoint pesan menyimpan `base64_image` di DB (sudah didukung model/schema), dan ketika agent memanggil LLM:
  - Deteksi apakah model mendukung vision (cek membership di MULTIMODAL_MODELS).
  - Jika ya, serialisasi pesan via `format_messages(..., supports_images=True)`. Jika tidak, hapus `base64_image` dan hanya kirim teks.
- Opsi lanjut: jika gambar besar, simpan juga ke sandbox (via SANDBOX_CLIENT) dan simpan path untuk tool lain; namun untuk LLM cukup base64.

## Perubahan Minimal di Backend (Checklist)
- Base agent
  - Tambah field opsional `llm_overrides: dict | None`.
  - Di `initialize_agent`, jika `llm_overrides` ada, buat instance `LLM` dengan `llm_config` hasil merge overrides + default, serta `config_name` unik (menghindari cache tertimpa).
- Agent factory
  - `Manus.create(**kwargs)` dan agent lain: biarkan meneruskan kwargs/field tanpa logika khusus; BaseAgent sudah meng-handle inisialisasi LLM.
- LLM
  - `LLM.__init__` sudah mendukung `llm_config: Optional[LLMSettings]`. Siapkan helper konversi dict->LLMSettings (atau konstruksi langsung bila tipe kompatibel) agar overrides mudah diterapkan.
  - Pastikan jalur pemanggilan `ask`/`ask_tool` menggunakan `format_messages(..., supports_images=is_multimodal(self.model))`. Jika sudah, tidak perlu ubah.
- Tasks/API
  - Saat membuat Conversation, terima `agent_type`, `llm_model`, `temperature`, dsb. Simpan ke DB (setidaknya `llm_model`).
  - Saat men-trigger agent (Celery), turunkan `agent_kwargs` berisi `llm_overrides` dari Conversation (atau dari request run) ke `*.create(**kwargs)`.
  - Endpoint kirim pesan mendukung field `base64_image` (sudah ada secara model), tidak perlu mengubah kontrak existing—cukup dokumentasikan di API dan pastikan diserialisasi ke LLM.
- Frontend (ringkas, untuk implementasi terpisah)
  - Tambah selector agent + selector model (dropdown). Simpan ke Conversation saat create.
  - Di form kirim pesan, dukung upload gambar; kirim sebagai `base64_image`.
- Persistensi File Sandbox -> FileArtifact
  - Agent: pastikan `attach_django_persistence` aktif sehingga `persist_files_hook` terpasang untuk Conversation yang berjalan. Hook ini akan membuat/memperbarui `FileArtifact` saat `agent.update_files(persist=True)` dipanggil.
  - Tools: setelah berhasil menulis/menyalin file ke sandbox (mis. di `SandboxFileOperator.write_file`, `StrReplaceEditor`, `PythonExecute`), panggil `agent.update_files(files=[path1, path2, ...], persist=True)` agar hook menyimpan metadata file ke DB dan broadcast ke UI.
  - Injeksi konteks agent ke tools:
    - Di `ToolCollection.execute`, sebelum mengeksekusi tool, set konteks agen pada instance tool. Contoh: jika tool memiliki atribut `tool_context`, isi dengan objek yang memuat referensi `agent` (atau langsung set `tool.agent = agent` jika tool mendukungnya). Gunakan `hasattr` agar backward-compatible.
    - Di tools yang menghasilkan file, gunakan konteks tersebut untuk memanggil `update_files` secara async setelah operasi file sukses.
  - Metadata file minimum yang dikirim cukup `path`; pengambilan size/hash dapat dilakukan di dalam hook menggunakan client sandbox sebelum menyimpan ke `FileArtifact`.

## Kontrak API (Rencana)
- POST /api/v1/chat/conversations
  - body: `{ title?, agent_type: "manus"|"data_analysis", llm_model?, temperature?, max_tokens? }`
  - response mencantumkan `llm_model` yang terset.
- POST /api/v1/chat/conversations/{id}/messages
  - body: `{ content: string, base64_image?: string }`
- POST /api/v1/chat/conversations/{id}/trigger-first-message
  - tetap, tanpa perubahan (override model bisa sudah dibawa saat create Conversation).
- (Opsional) GET /api/v1/chat/conversations/{id}/files
  - response: daftar `FileArtifact` terasosiasi untuk menampilkan file-file yang pernah dibuat di sandbox pada percakapan tersebut.

## Pseudocode Integrasi (Non-Kode Final)
- BaseAgent.initialize_agent:
  - if `llm_overrides` ada:
    - buat `unique_config_name` (gunakan conversation_id jika ada)
    - `self.llm = LLM(config_name=unique_config_name, llm_config=merge(default, overrides))`
  - else:
    - `self.llm = LLM(config_name=self.name.lower())`
- run_manus_agent(prompt, conversation_id, agent_kwargs):
  - muat Conversation -> bentuk `kwargs` termasuk `conversation_id`
  - jika Conversation punya `llm_model`/override lain -> `kwargs["llm_overrides"] = {...}`
  - `agent = await Manus.create(**kwargs)`
  - `await agent.run(None or prompt)`
- Saat memanggil LLM:
  - `supports_images = llm.model in MULTIMODAL_MODELS`
  - `formatted = LLM.format_messages(messages, supports_images)`
- Setelah tool menulis file di sandbox:
  - jika ada `agent` di konteks tool -> `await agent.update_files(files=[path], persist=True)`

## Strategi Cleanup Pesan Tool di Akhir Loop
- Tujuan: mengurangi token di percakapan berikutnya dengan membersihkan konten pesan `role="tool"` yang cenderung panjang (khususnya hasil `read`, `web_search`).
- Kapan: di tahap `cleanup` setelah loop agent selesai (mis. di `BaseAgent.run` bagian akhir atau override `ToolCallAgent.cleanup`).
- Ruang lingkup:
  - Deteksi pesan dengan `role="tool"` dan `tool_name` ∈ {`read`, `web_search`} (opsional: termasuk aksi `web_search` dari tool lain seperti browser).
  - Kosongkan atau ringkas `content` (mis. simpan ringkasan singkat: jumlah hasil, URL utama) dan hapus payload besar (teks panjang, base64).
  - Pertahankan metadata penting (tool name, status, timestamp) agar timeline percakapan tetap koheren.
  - Kirim event WebSocket `message_updated` ke frontend agar UI menyinkronkan perubahan.
- Konfigurasi: sediakan flag konfigurasi (global/per-conversation) untuk mengaktifkan/menonaktifkan cleanup ini guna keperluan debugging.

## Acceptance Criteria
- Tanpa override dari frontend, perilaku tetap sama persis seperti sekarang.
- Saat memilih model di UI, info model di header tetap tampil dan benar (tersimpan di Conversation), dan semua permintaan percakapan memakai model tersebut.
- Kirim pesan dengan gambar + teks pada model multimodal menghasilkan pemformatan `image_url` yang benar di request LLM; pada model non-multimodal, gambar diabaikan tanpa error.
- Mode Data Analysis menggunakan alur VisualizationPrepare + DataVisualization seperti sebelumnya; Manus tetap menjadi mode general-purpose.
- Semua existing tests/flow tetap hijau; tidak ada regresi pada tool chart_visualization.
- Saat tool membuat/menulis file di sandbox, entri `FileArtifact` tercipta/terbarui di DB dan terlihat di UI (serta tetap tersedia saat halaman/percakapan dibuka ulang).
- Setelah proses run selesai, pesan `role="tool"` untuk `read` dan `web_search` memiliki konten dikosongkan/diringkas sehingga tidak menambah token signifikan pada percakapan berikutnya.

## Risiko & Mitigasi
- Risiko: Cache instance LLM berbasis `config_name` dapat menyebabkan override tidak berefek jika memakai nama config yang sama. Mitigasi: gunakan `config_name` unik per conversation saat ada override, atau sediakan metode clone LLm khusus override.
- Risiko: Besar payload base64 di pesan. Mitigasi: batasi ukuran/kompresi di frontend; jika perlu, simpan file ke sandbox dan kirimkan versi kecil untuk LLM.
- Risiko: Backward compatibility. Mitigasi: semua field baru opsional dengan fallback ke config default.
- Risiko: Hilangnya konteks penting setelah cleanup pesan tool. Mitigasi: simpan ringkasan singkat atau pointer (mis. daftar URL) di field terpisah; sediakan toggle untuk mematikan cleanup saat debugging; atau simpan salinan lengkap ke log terpisah yang tidak ikut dipromote ke LLM.

## Rencana Rollout & Pengujian
- Unit test
  - BaseAgent inisialisasi llm dengan/ tanpa overrides; verifikasi `llm.model` benar.
  - format_messages dengan `supports_images` true/false memproses `base64_image` sesuai.
  - `persist_files_hook` dipanggil saat `agent.update_files(persist=True)` dan membuat/memperbarui `FileArtifact` dengan metadata minimal (path, size/hash bila tersedia).
  - Fungsi `cleanup` mengosongkan/memadatkan konten pesan tool (`read`, `web_search`) sesuai aturan.
- Integration test
  - Buat Conversation dengan `llm_model` tertentu, kirim pesan, verifikasi agent memakai model itu.
  - Kirim pesan dengan `base64_image`, verifikasi tersimpan di DB dan dipakai oleh LLM saat model multimodal.
  - Jalankan tool yang menulis file (mis. `SandboxFileOperator`), verifikasi `FileArtifact` tercatat dan webhook/WebSocket notifikasi terkirim.
  - Setelah run selesai, verifikasi pesan tool untuk `read`/`web_search` telah dibersihkan di DB dan UI ikut ter-update.
- E2E
  - Pilih agent di frontend, pilih model, kirim pesan teks+gambar; amati respons.
  - Gunakan tool yang menghasilkan file; reload halaman percakapan dan pastikan daftar file tetap ada.
  - Lakukan sesi percakapan berulang dan amati bahwa token context tidak membengkak akibat pesan tool hasil baca/crawl yang panjang.
- Observability
  - Tambah logging ringkas saat apply overrides dan saat deteksi multimodal.
  - Tambah logging saat `update_files` dipanggil (jumlah file, path) dan saat cleanup pesan tool (jumlah pesan dibersihkan, total byte sebelum/sesudah).