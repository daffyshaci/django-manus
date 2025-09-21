# Panduan Implementasi Split View Artifact (Django → Next.js)

Dokumen ini menjelaskan cara menerapkan UI split view (kiri: chat, kanan: artifact/editor) yang mirip dengan proyek ini, namun versi sederhana, untuk proyek lain yang backend AI‑nya memakai Django (mengirim event via WebSocket) dan frontend Next.js.

Fokus: ketika event `agent.create_file` (atau event serupa yang Anda pilih) diterima klien, panel Artifact muncul di kanan dan menampilkan dokumen/artifact tersebut.

---

## 1) Gambaran Arsitektur Sederhana
- Backend (Django/Channels): mengirim event melalui WebSocket ke client.
- Frontend (Next.js/React): 
  - Client WebSocket menerima event dan mengubah state "artifact" global.
  - Halaman Chat merender panel chat (kiri) + panel artifact (kanan) ketika `artifact.isVisible === true`.

---

## 2) Kontrak Event WebSocket (Minimal)
Gunakan 3 jenis event dasar agar sederhana:
- `agent.create_file:init` — inisialisasi artifact baru.
- `agent.create_file:chunk` — update konten bertahap (opsional, bisa langsung `finish`).
- `agent.create_file:finish` — finalisasi konten & tampilkan.
- (Opsional) `agent.create_file:clear` — tutup panel dan reset state.

Contoh payload:
```json
// init
{
  "type": "agent.create_file:init",
  "data": { "id": "doc-123", "kind": "text", "title": "Draft", "meta": {} }
}

// chunk (opsional, bisa banyak kali)
{
  "type": "agent.create_file:chunk",
  "data": { "id": "doc-123", "content": "…potongan konten…" }
}

// finish
{
  "type": "agent.create_file:finish",
  "data": { "id": "doc-123", "content": "Konten lengkap akhir" }
}

// clear (opsional)
{
  "type": "agent.create_file:clear",
  "data": { "id": "doc-123" }
}
```
Catatan: Anda bisa mengganti `agent.create_file` menjadi command/event lain (mis. `agent.create_document`, `agent.update_file`, dll.). Struktur handler di frontend tetap sama—cukup mapping `type`‑nya.

---

## 3) File yang Bisa Anda Salin dari Proyek Ini (opsional)
Jika ingin belajar dari implementasi lengkap, Anda bisa meninjau (dan mengadaptasi sebagian kecil) file berikut di proyek ini:
- `components/data-stream-provider.tsx` — contoh Context untuk menyalurkan data streaming ke komponen.
- `components/data-stream-handler.tsx` — contoh pola menerima sinyal dan update state artifact.
- `hooks/use-artifact.ts` — contoh hook state artifact (visible, id, kind, title, content, dsb.).
- `components/document-preview.tsx` — contoh preview inline di chat yang membuka panel artifact saat diklik.
- `components/artifact.tsx` — panel artifact lengkap (cukup kompleks). Untuk versi sederhana, gunakan pendekatan minimal di bawah.

Namun untuk versi SEDERHANA, disarankan implementasi baru (lebih ringkas) seperti pada langkah berikut, agar tidak banyak dependensi.

---

## 4) Implementasi Sederhana di Next.js (Langkah per Langkah)

### 4.1 Buat state global Artifact (Context + Hook)
Buat `contexts/ArtifactContext.tsx` (nama bebas) yang menyimpan:
- `isVisible: boolean`
- `id?: string`, `kind?: 'text'|'code'|'image'|string`, `title?: string`
- `content: string` (untuk contoh teks),
- `openArtifact(payload)`, `appendContent(text)`, `finishArtifact(content)`, `clearArtifact()`

Pseudo‑kode:
```tsx
import React, { createContext, useContext, useState, useCallback } from 'react';

type ArtifactState = {
  isVisible: boolean;
  id?: string;
  kind?: string;
  title?: string;
  content: string;
};

type Ctx = ArtifactState & {
  openArtifact: (p: { id: string; kind: string; title?: string }) => void;
  appendContent: (chunk: string) => void;
  finishArtifact: (full: string) => void;
  clearArtifact: () => void;
};

const ArtifactContext = createContext<Ctx | null>(null);

export function ArtifactProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ArtifactState>({ isVisible: false, content: '' });

  const openArtifact = useCallback((p: { id: string; kind: string; title?: string }) => {
    setState({ isVisible: true, id: p.id, kind: p.kind, title: p.title, content: '' });
  }, []);
  const appendContent = useCallback((chunk: string) => {
    setState(s => ({ ...s, content: s.content + chunk }));
  }, []);
  const finishArtifact = useCallback((full: string) => {
    setState(s => ({ ...s, content: full ?? s.content }));
  }, []);
  const clearArtifact = useCallback(() => {
    setState({ isVisible: false, content: '' });
  }, []);

  return (
    <ArtifactContext.Provider value={{ ...state, openArtifact, appendContent, finishArtifact, clearArtifact }}>
      {children}
    </ArtifactContext.Provider>
  );
}

export const useArtifact = () => {
  const ctx = useContext(ArtifactContext);
  if (!ctx) throw new Error('useArtifact must be used within ArtifactProvider');
  return ctx;
};
```

### 4.2 Buat WebSocket client dan handler event
Buat `lib/ws-client.ts` untuk koneksi ke Django Channels, lalu mapping event → action context di atas.

Pseudo‑kode:
```ts
import { useEffect } from 'react';
import { useArtifact } from '@/contexts/ArtifactContext';

export function useAgentSocket(url: string) {
  const { openArtifact, appendContent, finishArtifact, clearArtifact } = useArtifact();

  useEffect(() => {
    const ws = new WebSocket(url);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        switch (msg.type) {
          case 'agent.create_file:init':
            openArtifact({ id: msg.data.id, kind: msg.data.kind, title: msg.data.title });
            break;
          case 'agent.create_file:chunk':
            appendContent(msg.data.content || '');
            break;
          case 'agent.create_file:finish':
            finishArtifact(msg.data.content || '');
            break;
          case 'agent.create_file:clear':
            clearArtifact();
            break;
        }
      } catch {}
    };
    return () => ws.close();
  }, [openArtifact, appendContent, finishArtifact, clearArtifact, url]);
}
```
Anda bisa mengganti prefix `agent.create_file` ke command lain yang Anda pakai.

### 4.3 Panel Artifact sederhana (split layout)
Tambahkan komponen `components/ArtifactPanel.tsx` yang muncul di kanan jika `isVisible`.

Layout minimal (tanpa animasi):
```tsx
import { useArtifact } from '@/contexts/ArtifactContext';

export default function ArtifactPanel() {
  const { isVisible, title, content, clearArtifact } = useArtifact();
  if (!isVisible) return null;
  return (
    <aside style={{ width: '50%', borderLeft: '1px solid #eee', padding: 16, overflow: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3>{title || 'Artifact'}</h3>
        <button onClick={clearArtifact}>Close</button>
      </div>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{content}</pre>
    </aside>
  );
}
```

### 4.4 Integrasi di halaman Chat
Di halaman chat Anda (mis. `app/(chat)/page.tsx`), bungkus dengan `ArtifactProvider`, pakai hook `useAgentSocket`, dan buat layout dua kolom sederhana.

Pseudo‑kode layout:
```tsx
import ArtifactPanel from '@/components/ArtifactPanel';
import { ArtifactProvider } from '@/contexts/ArtifactContext';
import { useAgentSocket } from '@/lib/ws-client';

function ChatLeft() {
  // komponen chat Anda
  return <div style={{ padding: 16 }}>Chat Area</div>;
}

export default function ChatPage() {
  return (
    <ArtifactProvider>
      <ChatWithArtifact />
    </ArtifactProvider>
  );
}

function ChatWithArtifact() {
  useAgentSocket('wss://your-django-host/ws/agent/');
  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <main style={{ flex: 1 }}><ChatLeft /></main>
      <ArtifactPanel />
    </div>
  );
}
```

---

## 5) Django/Channels: contoh pengiriman event
Menyesuaikan dengan django channel yang ada sekarang

---

## 6) Opsi Penyederhanaan (dibanding proyek ini)
- Tidak perlu animasi transisi dari preview ke panel kanan.
- Tidak perlu versioning, diff, atau "artifact messages" di panel kanan.
- Satu jenis artifact dulu (mis. `kind: 'text'`) dengan tampilan `<pre>`; tipe lain bisa ditambah belakangan.
- Hindari dependensi UI kompleks; pakai CSS inline sederhana atau Tailwind dasar.

---

## 7) Mapping Command/Event yang bisa Anda pakai
- Buat nama event dasar: `agent.create_file`.
- Turunannya (disarankan): `agent.create_file:init`, `agent.create_file:chunk`, `agent.create_file:finish`, `agent.create_file:clear`.
- Untuk agent lain, cukup ganti prefix, mis. `agent.update_file:*`, `agent.create_document:*`.

---

## 8) Checklist Integrasi
1) Backend Django
- [ ] Endpoint WS siap (Channels consumer).
- [ ] Agent memanggil pengiriman event `init` → `chunk` (opsional) → `finish`.

2) Frontend Next.js
- [ ] Buat `ArtifactProvider` + `useArtifact`.
- [ ] Buat hook `useAgentSocket` untuk koneksi WS dan handler event.
- [ ] Buat `ArtifactPanel` sederhana.
- [ ] Integrasikan di halaman chat (layout dua kolom).
- [ ] Uji manual alur `init → finish`.

---

## 9) Debug & Troubleshooting
- Panel tidak muncul: cek `isVisible` berubah ke `true` saat `init`.
- Konten tidak ter‑update: pastikan `chunk`/`finish` mengisi `content`.
- WS sering putus: aktifkan retry / backoff sederhana (opsional) di `useAgentSocket`.

---

## 10) Keamanan & Performa Singkat
- Validasi payload di server; jangan kirim data sensitif ke WS publik.
- Batasi ukuran konten (chunking) untuk dokumen sangat besar.
- Render malas (lazy) editor/komponen berat hanya saat panel terbuka.

---

Dengan mengikuti langkah‑langkah di atas, Anda bisa mendapatkan pengalaman split view artifact yang mirip proyek ini, namun jauh lebih sederhana dan mudah diintegrasikan dengan backend Django yang mengirim event melalui WebSocket ke Next.js. Selanjutnya, Anda dapat bertahap menambahkan fitur lanjutan (preview inline, animasi, versioning, diff) meniru pola dari file‑file referensi pada proyek ini jika dibutuhkan.

## Quick Start (Versi Lite Tanpa Dependensi Berat)

Contoh minimal siap pakai tersedia di folder `examples/lite-artifact`:
- `ArtifactProvider.tsx`: provider + hook state artifact ringan
- `useAgentSocket.ts`: hook WebSocket untuk menerima event dari Django
- `ArtifactPanel.tsx`: panel artifact sederhana (split view kanan)

Layout minimal (tanpa animasi):
```tsx
import { useArtifact } from '@/contexts/ArtifactContext';

export default function ArtifactPanel() {
  const { isVisible, title, content, clearArtifact } = useArtifact();
  if (!isVisible) return null;
  return (
    <aside style={{ width: '50%', borderLeft: '1px solid #eee', padding: 16, overflow: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3>{title || 'Artifact'}</h3>
        <button onClick={clearArtifact}>Close</button>
      </div>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{content}</pre>
    </aside>
  );
}
```

### 4.4 Integrasi di halaman Chat
Di halaman chat Anda (mis. `app/(chat)/page.tsx`), bungkus dengan `ArtifactProvider`, pakai hook `useAgentSocket`, dan buat layout dua kolom sederhana.

Pseudo‑kode layout:
```tsx
import ArtifactPanel from '@/components/ArtifactPanel';
import { ArtifactProvider } from '@/contexts/ArtifactContext';
import { useAgentSocket } from '@/lib/ws-client';

function ChatLeft() {
  // komponen chat Anda
  return <div style={{ padding: 16 }}>Chat Area</div>;
}

export default function ChatPage() {
  return (
    <ArtifactProvider>
      <ChatWithArtifact />
    </ArtifactProvider>
  );
}

function ChatWithArtifact() {
  useAgentSocket('wss://your-django-host/ws/agent/');
  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <main style={{ flex: 1 }}><ChatLeft /></main>
      <ArtifactPanel />
    </div>
  );
}
```

---

## 5) Django/Channels: contoh pengiriman event
Menyesuaikan dengan django channel yang ada sekarang

---

## 6) Opsi Penyederhanaan (dibanding proyek ini)
- Tidak perlu animasi transisi dari preview ke panel kanan.
- Tidak perlu versioning, diff, atau "artifact messages" di panel kanan.
- Satu jenis artifact dulu (mis. `kind: 'text'`) dengan tampilan `<pre>`; tipe lain bisa ditambah belakangan.
- Hindari dependensi UI kompleks; pakai CSS inline sederhana atau Tailwind dasar.

---

## 7) Mapping Command/Event yang bisa Anda pakai
- Buat nama event dasar: `agent.create_file`.
- Turunannya (disarankan): `agent.create_file:init`, `agent.create_file:chunk`, `agent.create_file:finish`, `agent.create_file:clear`.
- Untuk agent lain, cukup ganti prefix, mis. `agent.update_file:*`, `agent.create_document:*`.

---

## 8) Checklist Integrasi
1) Backend Django
- [ ] Endpoint WS siap (Channels consumer).
- [ ] Agent memanggil pengiriman event `init` → `chunk` (opsional) → `finish`.

2) Frontend Next.js
- [ ] Buat `ArtifactProvider` + `useArtifact`.
- [ ] Buat hook `useAgentSocket` untuk koneksi WS dan handler event.
- [ ] Buat `ArtifactPanel` sederhana.
- [ ] Integrasikan di halaman chat (layout dua kolom).
- [ ] Uji manual alur `init → finish`.

---

## 9) Debug & Troubleshooting
- Panel tidak muncul: cek `isVisible` berubah ke `true` saat `init`.
- Konten tidak ter‑update: pastikan `chunk`/`finish` mengisi `content`.
- WS sering putus: aktifkan retry / backoff sederhana (opsional) di `useAgentSocket`.

---

## 10) Keamanan & Performa Singkat
- Validasi payload di server; jangan kirim data sensitif ke WS publik.
- Batasi ukuran konten (chunking) untuk dokumen sangat besar.
- Render malas (lazy) editor/komponen berat hanya saat panel terbuka.

---

Dengan mengikuti langkah‑langkah di atas, Anda bisa mendapatkan pengalaman split view artifact yang mirip proyek ini, namun jauh lebih sederhana dan mudah diintegrasikan dengan backend Django yang mengirim event melalui WebSocket ke Next.js. Selanjutnya, Anda dapat bertahap menambahkan fitur lanjutan (preview inline, animasi, versioning, diff) meniru pola dari file‑file referensi pada proyek ini jika dibutuhkan.

## Quick Start (Versi Lite Tanpa Dependensi Berat)

Contoh minimal siap pakai tersedia di folder `examples/lite-artifact`:
- `ArtifactProvider.tsx`: provider + hook state artifact ringan
- `useAgentSocket.ts`: hook WebSocket untuk menerima event dari Django
- `ArtifactPanel.tsx`: panel artifact sederhana (split view kanan)

Layout minimal (tanpa animasi):
```tsx
import { useArtifact } from '@/contexts/ArtifactContext';

export default function ArtifactPanel() {
  const { isVisible, title, content, clearArtifact } = useArtifact();
  if (!isVisible) return null;
  return (
    <aside style={{ width: '50%', borderLeft: '1px solid #eee', padding: 16, overflow: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3>{title || 'Artifact'}</h3>
        <button onClick={clearArtifact}>Close</button>
      </div>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{content}</pre>
    </aside>
  );
}
```

## 14) Panel Kanan Kustom (Non-Artifact): File Viewer Split (Left Tree + Right Content)
Tujuan: Membuat panel kanan terpisah dari sistem Artifact, berisi dua sisi — kiri: daftar/tree file, kanan: area konten. Saat item file diklik, konten file dirender di sisi kanan. Cocok untuk kebutuhan viewer/editor ringan.

Arsitektur ringan mirip versi Lite (Provider + hook + Panel UI), jadi mudah diintegrasikan ke Chat tanpa menyentuh sistem Artifact yang sudah ada.

### 14.1 Provider dan Hook
Menyediakan state global panel, daftar file, file terpilih, dan kontennya.

```tsx
"use client";
import React, { createContext, useContext, useReducer, ReactNode } from "react";

export type FileItem = {
  id: string;
  name: string;
  path?: string;
  isDir?: boolean;
  children?: FileItem[];
};

export type FileViewerState = {
  isVisible: boolean;
  files: FileItem[];
  selectedId?: string;
  contentById: Record<string, string>;
};

const initialState: FileViewerState = {
  isVisible: false,
  files: [],
  selectedId: undefined,
  contentById: {},
};

type Action =
  | { type: "OPEN"; payload: { files: FileItem[]; selectedId?: string } }
  | { type: "CLOSE" }
  | { type: "SELECT"; payload: { id: string } }
  | { type: "SET_CONTENT"; payload: { id: string; content: string } };

function reducer(state: FileViewerState, action: Action): FileViewerState {
  switch (action.type) {
    case "OPEN": {
      const { files, selectedId } = action.payload;
      return { ...state, isVisible: true, files, selectedId };
    }
    case "CLOSE":
      return { ...state, isVisible: false };
    case "SELECT":
      return { ...state, selectedId: action.payload.id };
    case "SET_CONTENT": {
      const { id, content } = action.payload;
      return { ...state, contentById: { ...state.contentById, [id]: content } };
    }
    default:
      return state;
  }
}

const Ctx = createContext<{
  state: FileViewerState;
  actions: {
    open: (files: FileItem[], selectedId?: string) => void;
    close: () => void;
    select: (id: string) => void;
    setContent: (id: string, content: string) => void;
  };
} | null>(null);

export function FileViewerProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const actions = {
    open: (files: FileItem[], selectedId?: string) =>
      dispatch({ type: "OPEN", payload: { files, selectedId } }),
    close: () => dispatch({ type: "CLOSE" }),
    select: (id: string) => dispatch({ type: "SELECT", payload: { id } }),
    setContent: (id: string, content: string) =>
      dispatch({ type: "SET_CONTENT", payload: { id, content } }),
  } as const;

  return <Ctx.Provider value={{ state, actions }}>{children}</Ctx.Provider>;
}

export function useFileViewer() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useFileViewer must be used within FileViewerProvider");
  return ctx;
}
```

### 14.2 Panel UI (Slide-in Right) + Split Kiri/Kanan
Panel kanan dengan animasi slide/fade. Kiri: daftar/tree file. Kanan: konten dari file terpilih.

```tsx
"use client";
import { AnimatePresence, motion } from "framer-motion";
import { useFileViewer, FileItem } from "./file-viewer-provider"; // sesuaikan path

export function FileViewerPanel() {
  const { state, actions } = useFileViewer();
  const { isVisible, files, selectedId, contentById } = state;

  const currentContent = selectedId ? contentById[selectedId] ?? "" : "";

  return (
    <AnimatePresence initial={false}>
      {isVisible && (
        <motion.aside
          key="file-viewer-panel"
          initial={{ x: 320, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 320, opacity: 0 }}
          transition={{ type: "spring", stiffness: 260, damping: 28 }}
          className="fixed right-0 top-0 z-40 h-screen w-[90vw] max-w-[920px] border-l bg-background shadow-xl"
          aria-label="File Viewer Panel"
        >
          <header className="flex items-center justify-between border-b p-3">
            <h3 className="font-semibold">Files</h3>
            <button
              className="rounded-md border px-2 py-1 text-sm hover:bg-accent"
              onClick={actions.close}
            >
              Close
            </button>
          </header>

          <div className="flex h-[calc(100vh-48px)]">
            {/* Kiri: Tree/List */}
            <div className="w-1/3 min-w-[220px] max-w-[380px] border-r p-2">
              <FilesTree files={files} selectedId={selectedId} onSelect={actions.select} />
            </div>

            {/* Kanan: Content */}
            <div className="flex-1 p-4">
              {selectedId ? (
                <pre className="h-full w-full overflow-auto whitespace-pre-wrap text-sm">
                  {currentContent || "Pilih file untuk melihat konten atau muat konten secara lazy."}
                </pre>
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  Pilih salah satu file di sebelah kiri
                </div>
              )}
            </div>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

function FilesTree({ files, selectedId, onSelect }: {
  files: FileItem[];
  selectedId?: string;
  onSelect: (id: string) => void;
}) {
  return (
    <ul className="space-y-1 text-sm">
      {files.map((f) => (
        <TreeNode key={f.id} node={f} selectedId={selectedId} onSelect={onSelect} level={0} />)
      )}
    </ul>
  );
}

function TreeNode({ node, selectedId, onSelect, level }: {
  node: FileItem;
  selectedId?: string;
  onSelect: (id: string) => void;
  level: number;
}) {
  const isSelected = node.id === selectedId;
  const padding = 8 + level * 12; // indent
  const isDir = !!node.isDir;
  return (
    <li>
      <div
        style={{ paddingLeft: padding }}
        className={`flex cursor-pointer items-center rounded px-2 py-1 hover:bg-accent ${
          isSelected ? "bg-accent" : ""
        }`}
        onClick={() => onSelect(node.id)}
      >
        <span className="mr-2 text-muted-foreground">{isDir ? "📁" : "📄"}</span>
        <span className="truncate">{node.name}</span>
      </div>
      {node.children && node.children.length > 0 && (
        <ul className="mt-1 space-y-1">
          {node.children.map((c) => (
            <TreeNode
              key={c.id}
              node={c}
              selectedId={selectedId}
              onSelect={onSelect}
              level={level + 1}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
```

Tips:
- Anda bisa memuat konten secara lazy: saat onSelect dipanggil, set placeholder (mis. "Loading...") lalu fetch konten dan panggil actions.setContent(id, hasilFetch).
- Untuk code highlighting atau render markdown, tambahkan renderer khusus pada area konten.

### 14.3 Integrasi ke Layout/Chat
1) Bungkus area Chat dengan provider ini (mis. di app/(chat)/layout.tsx):

```tsx
// app/(chat)/layout.tsx (contoh)
import { FileViewerProvider } from "@/examples/your-path/file-viewer-provider"; // sesuaikan path

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <FileViewerProvider>
      {children}
      {/* Pasang panel di root agar melayang di atas chat */}
      {/* <FileViewerPanel /> */}
    </FileViewerProvider>
  );
}
```

2) Render panel di atas Chat (mis. di app/(chat)/page.tsx atau di layout setelah provider):

```tsx
// app/(chat)/page.tsx (cuplikan)
import { FileViewerPanel } from "@/examples/your-path/file-viewer-panel"; // sesuaikan path

export default async function Page() {
  // ... kode autentikasi
  return (
    <>
      {/* ... Chat, DataStreamHandler, dll ... */}
      <FileViewerPanel />
    </>
  );
}
```

3) Buka panel dari tombol/link mana pun, dengan data files dan konten awal:

```tsx
"use client";
import { useFileViewer, type FileItem } from "@/examples/your-path/file-viewer-provider";

const sampleFiles: FileItem[] = [
  { id: "readme", name: "README.md" },
  {
    id: "src",
    name: "src",
    isDir: true,
    children: [
      { id: "app_tsx", name: "app.tsx" },
      { id: "utils_ts", name: "utils.ts" },
    ],
  },
];

export function OpenFileViewerButton() {
  const { actions } = useFileViewer();
  return (
    <button
      className="rounded-md border px-2 py-1 text-sm hover:bg-accent"
      onClick={() => {
        actions.open(sampleFiles, "readme");
        // Beri konten awal (opsional), sisanya bisa di-load saat select
        actions.setContent("readme", "# README\nHalo dari File Viewer Panel");
        actions.setContent("app_tsx", "export default function App() { return <div>Hello</div> }");
      }}
    >
      Buka File Viewer
    </button>
  );
}
```

4) Lazy loading saat pilih file (opsional):

```tsx
function onSelectFile(id: string) {
  actions.select(id);
  actions.setContent(id, "Loading...");
  // Lakukan fetch ke backend Anda, lalu:
  // actions.setContent(id, fetchedText);
}
```

### 14.4 Catatan
- Panel ini sepenuhnya terpisah dari sistem Artifact. Anda dapat menjalankannya berdampingan tanpa saling mengganggu.
- Untuk aksesibilitas, pindahkan fokus ke panel saat terbuka dan sediakan keyboard nav untuk file list.
- Anda bisa mengganti width panel, menambahkan resizable split, dan menambah toolbar (search, refresh) sesuai kebutuhan.
- Animasi memakai framer-motion (sudah kita gunakan sebelumnya); pastikan paket terinstal.