# Next.js Helpers: REST dan WebSocket (Clerk + Django)

Dokumen ini berisi helper REST dan WebSocket yang siap pakai untuk Next.js (App Router, TypeScript) agar terintegrasi dengan backend Django OpenManus yang memakai token Clerk (Bearer) di REST dan query `?token=` untuk WebSocket.

## Prasyarat
- Next.js App Router + TypeScript.
- Clerk di frontend.
- Variabel lingkungan berikut (sesuaikan domain):

```env
# untuk pemanggilan REST di server (Route Handlers/Server Actions)
API_BASE_URL=https://your-django-domain

# untuk pemanggilan REST di browser (Client Components)
NEXT_PUBLIC_API_BASE_URL=https://your-django-domain

# base URL WebSocket (gunakan wss di production)
NEXT_PUBLIC_WS_BASE_URL=wss://your-django-domain/ws
```

Struktur file yang disarankan di proyek Next.js Anda:
- `src/lib/server/rest.ts`
- `src/lib/client/useRestFetch.ts`
- `src/lib/client/ws.ts`

---
## 1) REST helper (Server) — `src/lib/server/rest.ts`
Gunakan di Server Components/Route Handlers/Server Actions. Mengambil token Clerk via `auth()` dan menambahkan header `Authorization: Bearer <token>`.

```ts
"use server";
import { auth } from "@clerk/nextjs/server";

type Json = Record<string, any>;
const API_BASE = process.env.API_BASE_URL;
if (!API_BASE) throw new Error("Missing env API_BASE_URL");

export async function restFetch<T = Json>(path: string, init?: RequestInit): Promise<T> {
  const { getToken } = auth();
  const token = await getToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(init?.headers || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers, cache: "no-store" });
  if (!res.ok) throw new Error(`REST ${res.status} ${res.statusText}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

// Contoh pemakaian (sesuaikan dengan backend OpenManus)
export async function createConversation(body: {
  model: string;
  content: string;
  agent_type?: string;
  llm_overrides?: Record<string, any>;
}) {
  return restFetch("/v1/chat/conversations", { method: "POST", body: JSON.stringify(body) });
}

export async function sendMessage(convId: string, content: string) {
  return restFetch(`/v1/chat/conversations/${convId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}
```

---
## 2) REST helper (Client) — `src/lib/client/useRestFetch.ts`
Gunakan di Client Components. Mengambil token via `useAuth()` lalu menambahkan header Authorization.

```ts
"use client";
import { useAuth } from "@clerk/nextjs";

type Json = Record<string, any>;
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;

export function useRestFetch() {
  const { getToken } = useAuth();

  async function restFetchClient<T = Json>(path: string, init?: RequestInit): Promise<T> {
    const token = await getToken();
    const headers: HeadersInit = {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
    const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
    if (!res.ok) throw new Error(`REST ${res.status} ${res.statusText}: ${await res.text()}`);
    return res.json() as Promise<T>;
  }

  return { restFetch: restFetchClient };
}
```

Pemakaian singkat (Client):
```ts
const { restFetch } = useRestFetch();
await restFetch("/v1/chat/conversations", {
  method: "POST",
  body: JSON.stringify({ model: "gpt-4o-mini", content: "Halo" }),
});
```

---
## 3) WebSocket connector (Client) — `src/lib/client/ws.ts`
Backend menerima token JWT via query `?token=...`. Hook di bawah membangun URL WS, membuka koneksi, dan menyediakan helper `send`.

```ts
"use client";
import { useEffect, useRef } from "react";
import { useAuth } from "@clerk/nextjs";

type WSOptions = {
  conversationId: string | number;
  onMessage?: (data: any) => void;
  onOpen?: () => void;
  onClose?: (ev: CloseEvent) => void;
  onError?: (ev: Event) => void;
};

const WS_BASE = process.env.NEXT_PUBLIC_WS_BASE_URL; // e.g. wss://your-domain/ws

export function useConversationWS(opts: WSOptions) {
  const { conversationId, onMessage, onOpen, onClose, onError } = opts;
  const { getToken } = useAuth();
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let mounted = true;
    (async () => {
      const token = await getToken();
      const url = `${WS_BASE}/conversations/${conversationId}/?token=${encodeURIComponent(token || "")}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => mounted && onOpen?.();
      ws.onmessage = (evt) => {
        if (!mounted) return;
        try { onMessage?.(JSON.parse(evt.data)); }
        catch { onMessage?.(evt.data); }
      };
      ws.onerror = (ev) => mounted && onError?.(ev);
      ws.onclose = (ev) => mounted && onClose?.(ev);
    })();

    return () => {
      mounted = false;
      try { wsRef.current?.close(); } catch {}
      wsRef.current = null;
    };
  }, [conversationId, getToken, onClose, onError, onMessage, onOpen]);

  return {
    send: (payload: any) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
      wsRef.current.send(typeof payload === "string" ? payload : JSON.stringify(payload));
      return true;
    },
    readyState: () => wsRef.current?.readyState,
    close: () => wsRef.current?.close(),
  };
}
```

Pemakaian singkat (Client Component):
```tsx
"use client";
import { useState } from "react";
import { useConversationWS } from "@/lib/client/ws";

export default function WSExample({ conversationId }: { conversationId: string }) {
  const [events, setEvents] = useState<any[]>([]);
  const ws = useConversationWS({
    conversationId,
    onMessage: (evt) => setEvents((prev) => [...prev, evt]),
  });

  return (
    <div>
      <button onClick={() => ws.send({ type: "ping" })}>Send Ping</button>
      <pre>{JSON.stringify(events, null, 2)}</pre>
    </div>
  );
}
```

---
## 4) Contoh alur end-to-end (singkat)
- REST:
  - `POST /v1/chat/conversations` body: `{ model, content, agent_type?, llm_overrides? }` → balikan berisi `id`.
  - `POST /v1/chat/conversations/{id}/messages` body: `{ content }`.
- WebSocket:
  - Koneksi ke: `{NEXT_PUBLIC_WS_BASE_URL}/conversations/{id}/?token=<jwt>`.
  - Terima event push JSON dari backend.

---
## 5) Catatan produksi
- Gunakan HTTPS/WSS dan domain tepercaya.
- Pastikan reverse proxy (Nginx/Cloudflare) mendukung upgrade WebSocket.
- Bila tidak memakai Clerk, modifikasi helper untuk menerima token secara eksplisit (props/argumen) dan sisipkan ke header/URL.