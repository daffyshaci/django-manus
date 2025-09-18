"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { useRestFetch } from "@/lib/client/useRestFetch";
import { useConversationWS } from "@/lib/client/ws";
// Replace custom rendering with ai-elements
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  Message as AiMessage,
  MessageAvatar,
  MessageContent,
} from "@/components/ai-elements/message";
import { Response as AiResponse } from "@/components/ai-elements/response";
import { Image as AIImage } from "@/components/ai-elements/image";
import { PromptInput } from "@/components/ai-elements/prompt-input";
import { Tool, ToolContent, ToolHeader, ToolOutput } from "@/components/ai-elements/tool";

// Types aligned with backend app/api.py schemas
// ConversationSchema -> { id, title, llm_model }
interface ConversationSchema {
  id: string;
  title: string;
  llm_model: string;
}

// MessageSchema -> see app/api.py
interface MessageSchema {
  id: string;
  conversation_id: string;
  role: "system" | "user" | "assistant" | "tool" | string;
  content?: string | null;
  tool_calls?: Record<string, unknown>[] | null;
  tool_call_id?: string | null;
  base64_image?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

interface ConversationDetailSchema {
  conversation: ConversationSchema;
  messages: MessageSchema[];
  message_count: number;
  total_cost: number;
  first_initiate: boolean;
}

// Narrow unknown to MessageSchema if it looks like one
function isMessageSchema(v: unknown): v is MessageSchema {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    typeof o.conversation_id === "string" &&
    typeof o.role === "string"
  );
}

// Handle possible WS payloads like { event: "message.created", payload: { ...Message } }
function extractMessageFromWS(data: unknown): MessageSchema | null {
  if (isMessageSchema(data)) return data;
  if (data && typeof data === "object") {
    const o = data as Record<string, unknown>;
    const payload = o.payload as unknown;

    if (typeof o.event === "string") {
      // Case A: { event, payload: Message }
      if (isMessageSchema(payload)) {
        return payload as MessageSchema;
      }
      // Case B: { event, payload: { message: Message } }
      if (payload && typeof payload === "object") {
        const pl = payload as Record<string, unknown>;
        const msgCandidate = pl["message"] as unknown;
        if (isMessageSchema(msgCandidate)) {
          return msgCandidate as MessageSchema;
        }
      }
    }
  }
  return null;
}

export default function ChatPage() {
  const params = useParams();
  const router = useRouter();
  const { isSignedIn, getToken: clerkGetToken } = useAuth();
  const conversationId = useMemo(() => {
    const raw = params?.["conversation_id"];
    return Array.isArray(raw) ? raw[0] : (raw as string);
  }, [params]);

  const { restFetch } = useRestFetch({
    getToken: async () => (await clerkGetToken?.({ template: "manus" })) ?? null,
  });

  const [conversation, setConversation] = useState<ConversationSchema | null>(null);
  const [messages, setMessages] = useState<MessageSchema[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Initial fetch conversation detail + messages
  useEffect(() => {
    let mounted = true;
    (async () => {
      if (!conversationId) return;
      try {
        setLoading(true);
        setError(null);
        const detail = await restFetch<ConversationDetailSchema>(`/v1/chat/conversations/${conversationId}`);
        if (!mounted) return;
        setConversation(detail.conversation);
        setMessages((detail.messages || []).slice().sort((a, b) => {
          const ta = a.created_at ? Date.parse(a.created_at) : 0;
          const tb = b.created_at ? Date.parse(b.created_at) : 0;
          return ta - tb; // ascending
        }));
        // trigger-first-message dihapus karena backend kini memulai Celery task saat create_conversation
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
      } finally {
        setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [conversationId, restFetch]);

  // WebSocket for realtime updates
  useConversationWS({
    conversationId: conversationId || "",
    getToken: async () => (await clerkGetToken?.({ template: "manus" })) ?? null,
    onMessage: (data) => {
      const msg = extractMessageFromWS(data);
      if (msg && msg.conversation_id === conversationId) {
        setMessages((prev) => {
          // Avoid duplicates by id
          if (prev.some((m) => m.id === msg.id)) return prev;
          const next = [...prev, msg];
          next.sort((a, b) => {
            const ta = a.created_at ? Date.parse(a.created_at) : 0;
            const tb = b.created_at ? Date.parse(b.created_at) : 0;
            return ta - tb;
          });
          return next;
        });
      }
    },
  });

  async function handlePromptSubmit(
    message: { text?: string; files?: { url?: string | null; mediaType?: string | null }[] },
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();
    if (!conversationId) return;
    const content = (message.text || "").trim();
    if (!content) return;

    try {
      // Optimistic append user message (without real id)
      const temp: MessageSchema = {
        id: `temp-${Date.now()}`,
        conversation_id: conversationId,
        role: "user",
        content,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, temp]);

      // Build request body, include first image (optional) as base64 if available
      let base64_image: string | undefined = undefined;
      const first = message.files?.[0];
      if (first?.url) {
        try {
          const resp = await fetch(first.url);
          const buf = await resp.arrayBuffer();
          const bin = String.fromCharCode(...new Uint8Array(buf));
          base64_image = btoa(bin);
        } catch {
          // ignore attachment errors
        }
      }

      await restFetch(`/v1/chat/conversations/${conversationId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content, ...(base64_image ? { base64_image } : {}) }),
      });
      // The real assistant responses will come via WS
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    }
  }

  if (!isSignedIn) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <p className="text-sm text-gray-600">Anda harus login untuk mengakses percakapan.</p>
      </div>
    );
  }

  if (!conversationId) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <p className="text-sm text-red-600">Conversation ID tidak valid.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex h-[100dvh] max-w-3xl flex-col p-0">
      <div className="flex items-center justify-between p-4">
        <button
          type="button"
          onClick={() => router.push("/")}
          className="text-sm text-blue-600 hover:underline"
        >
          ← Kembali
        </button>
        <div className="text-sm text-gray-500">{conversation?.llm_model}</div>
      </div>

      <Conversation className="flex-1">
        <ConversationContent>
          {loading && (
            <div className="p-4 text-sm text-gray-500">Memuat percakapan...</div>
          )}
          {error && (
            <div className="m-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {!loading && messages.length === 0 && !error ? (
            <ConversationEmptyState title="Belum ada pesan" description="Mulai percakapan dengan mengetik pesan di bawah" />
          ) : null}

          {messages.map((m) => {
            const from: "user" | "assistant" = m.role === "user" ? "user" : "assistant";
            const showAsTool = m.role === "tool";
            return (
              <div key={m.id}>
                {showAsTool ? (
                  <Tool defaultOpen className="max-w-[80%]" key={`tool-${m.id}`}>
                    <ToolHeader type={`tool-${m.tool_call_id ?? "call"}` as `tool-${string}`} state="output-available" />
                    <ToolContent>
                      <ToolOutput output={m.content ?? undefined} errorText={undefined} />
                    </ToolContent>
                  </Tool>
                ) : (
                  <AiMessage from={from} className="">
                    <MessageAvatar
                      src={from === "user" ? "/window.svg" : "/globe.svg"}
                      name={from === "user" ? "You" : "AI"}
                    />
                    <MessageContent>
                      {m.base64_image ? (
                        <div className="mt-2">
                          <AIImage base64={m.base64_image} uint8Array={new Uint8Array(0)} mediaType="image/png" alt="image" />
                        </div>
                      ) : null}
                      <AiResponse>{m.content || ""}</AiResponse>
                    </MessageContent>
                  </AiMessage>
                )}
              </div>
            );
          })}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      <div className="sticky bottom-0 w-full border-t bg-background p-2">
        <PromptInput
          accept="image/*"
          multiple={false}
          onSubmit={handlePromptSubmit}
          className="mx-auto w-full max-w-3xl"
        />
      </div>
    </div>
  );
}
