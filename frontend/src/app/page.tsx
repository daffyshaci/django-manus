"use client";

import { useCallback, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import {
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputToolbar,
  PromptInputSubmit,
} from "@/components/ai-elements/prompt-input";
import { Conversation, ConversationContent, ConversationEmptyState } from "@/components/ai-elements/conversation";
import { useRestFetch } from "@/lib/client/useRestFetch";

export default function Home() {
  const router = useRouter();
  const { getToken: clerkGetToken } = useAuth();
  const getToken = useCallback(async () => (await clerkGetToken?.({ template: "manus" })) ?? null, [clerkGetToken]);
  const { restFetch } = useRestFetch({ getToken });
  const [sending, setSending] = useState(false);

  const handleSubmit = useCallback(
    async (message: { text?: string | undefined }) => {
      const text = (message.text || "").trim();
      if (!text) return;

      setSending(true);
      try {
        // Buat percakapan baru dengan pesan pertama (backend akan memulai proses asinkron/Celery)
        const created = await restFetch<unknown>("/v1/chat/conversations", {
          method: "POST",
          body: JSON.stringify({ model: "gpt-4o-mini", content: text }),
        });

        // Ambil id dari beberapa kemungkinan bentuk respons
        const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
        let newId: string | number | null = null;
        if (isRecord(created)) {
          if ("id" in created && (typeof created.id === "string" || typeof created.id === "number")) {
            newId = created.id as string | number;
          } else if (
            "conversation" in created &&
            isRecord(created.conversation) &&
            "id" in created.conversation &&
            (typeof created.conversation.id === "string" || typeof created.conversation.id === "number")
          ) {
            newId = created.conversation.id as string | number;
          } else if (
            "data" in created &&
            isRecord(created.data) &&
            "id" in created.data &&
            (typeof created.data.id === "string" || typeof created.data.id === "number")
          ) {
            newId = created.data.id as string | number;
          } else if (
            "result" in created &&
            isRecord(created.result) &&
            "id" in created.result &&
            (typeof created.result.id === "string" || typeof created.result.id === "number")
          ) {
            newId = created.result.id as string | number;
          }
        }

        if (newId == null) {
          console.warn("Create conversation response did not include an id", created);
          return;
        }

        // Redirect ke halaman chat sesuai requirement
        router.push(`/chat/${newId}`);
      } catch (err) {
        console.error("Failed to create conversation:", err);
      } finally {
        setSending(false);
      }
    },
    [restFetch, router]
  );

  return (
    <div className="flex min-h-screen flex-col">
      <Conversation className="flex-1">
        <ConversationContent className="mx-auto w-full max-w-3xl">
          <ConversationEmptyState title="Mulai percakapan" description="Tulis pesan pertama Anda untuk memulai" />
        </ConversationContent>
      </Conversation>

      <div className="border-t bg-background/60 p-2 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto w-full max-w-3xl">
          <PromptInput onSubmit={handleSubmit}>
            <PromptInputBody>
              <PromptInputTextarea placeholder="Tulis pesan Anda dan tekan Enter untuk memulai" rows={3} />
            </PromptInputBody>
            <PromptInputToolbar>
              <div />
              <PromptInputSubmit disabled={sending}>{sending ? "Mengirim..." : "Kirim"}</PromptInputSubmit>
            </PromptInputToolbar>
          </PromptInput>
        </div>
      </div>
    </div>
  );
}
