"use client";

import { FormEvent, KeyboardEvent, useCallback, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarSeparator,
  SidebarTrigger,
} from "@/components/ui/sidebar";

import { Textarea } from "@/components/ui/textarea";
import { useRestFetch } from "@/lib/client/useRestFetch";
import {
  FileTextIcon,
  HistoryIcon,
  LightbulbIcon,
  LifeBuoyIcon,
  ListChecksIcon,
  Loader2Icon,
  PlusIcon,
  SendIcon,
  SettingsIcon,
  SparklesIcon,
} from "lucide-react";

const suggestions = [
  {
    title: "Ringkas dokumen hukum panjang",
    description: "Sorot klausul penting dan potensi risiko tanpa kehilangan konteks.",
    icon: FileTextIcon,
  },
  {
    title: "Susun ide argumen persuasif",
    description: "Bangun kerangka argumen yang runtut untuk presentasi atau sidang.",
    icon: LightbulbIcon,
  },
  {
    title: "Buat daftar langkah eksekusi",
    description: "Uraikan rencana tindakan terstruktur dari dokumen atau arahan yang kompleks.",
    icon: ListChecksIcon,
  },
  {
    title: "Eksplorasi variasi strategi baru",
    description: "Minta alternatif pendekatan untuk masalah yang sama secara kreatif.",
    icon: SparklesIcon,
  },
] as const;

export default function Home() {
  const router = useRouter();
  const { getToken: clerkGetToken } = useAuth();
  const getToken = useCallback(
    async () => (await clerkGetToken?.({ template: "manus" })) ?? null,
    [clerkGetToken]
  );
  const { restFetch } = useRestFetch({ getToken });
  const [sending, setSending] = useState(false);
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const handleSubmit = useCallback(
    async (message: { text?: string | undefined }) => {
      const text = (message.text || "").trim();
      if (!text) return;

      setSending(true);
      try {
        const created = await restFetch<unknown>("/v1/chat/conversations", {
          method: "POST",
          body: JSON.stringify({ model: "deepseek-chat", content: text }),
        });

        const isRecord = (v: unknown): v is Record<string, unknown> =>
          typeof v === "object" && v !== null;
        let newId: string | number | null = null;
        if (isRecord(created)) {
          if (
            "id" in created &&
            (typeof created.id === "string" || typeof created.id === "number")
          ) {
            newId = created.id as string | number;
          } else if (
            "conversation" in created &&
            isRecord(created.conversation) &&
            "id" in created.conversation &&
            (typeof created.conversation.id === "string" ||
              typeof created.conversation.id === "number")
          ) {
            newId = created.conversation.id as string | number;
          } else if (
            "data" in created &&
            isRecord(created.data) &&
            "id" in created.data &&
            (typeof created.data.id === "string" ||
              typeof created.data.id === "number")
          ) {
            newId = created.data.id as string | number;
          } else if (
            "result" in created &&
            isRecord(created.result) &&
            "id" in created.result &&
            (typeof created.result.id === "string" ||
              typeof created.result.id === "number")
          ) {
            newId = created.result.id as string | number;
          }
        }

        if (newId == null) {
          console.warn("Create conversation response did not include an id", created);
          return;
        }

        router.push(`/chat/${newId}`);
      } catch (err) {
        console.error("Failed to create conversation:", err);
      } finally {
        setSending(false);
      }
    },
    [restFetch, router]
  );

  const sendPrompt = useCallback(async () => {
    if (sending) return;
    const text = input.trim();
    if (!text) return;

    await handleSubmit({ text });
    setInput("");
  }, [handleSubmit, input, sending]);

  const onSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      await sendPrompt();
    },
    [sendPrompt]
  );

  const onTextareaKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        void sendPrompt();
      }
    },
    [sendPrompt]
  );

  const handleSuggestionClick = (value: string) => {
    setInput(value);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
    });
  };

  const handleStartNewChat = () => {
    handleSuggestionClick("");
    router.push("/");
  };

  return (
    <div className="h-screen flex flex-col items-center justify-center">
      <div className="mx-auto w-full max-w-3xl">
        <form
          onSubmit={onSubmit}
          className="rounded-3xl border bg-background/95 shadow-lg transition focus-within:border-primary/40 focus-within:shadow-xl"
        >
          <div className="px-5 pt-5">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={onTextareaKeyDown}
              placeholder="Tulis pesan Anda dan tekan Enter untuk mulai berbicara"
              rows={1}
              disabled={sending}
              className="min-h-[72px] resize-none border-none bg-transparent p-0 text-base focus-visible:ring-0 focus-visible:ring-offset-0"
            />
          </div>
          <div className="flex items-center justify-between gap-4 px-5 pb-5 pt-3">
            <p className="text-xs text-muted-foreground">
              Tekan Enter untuk mengirim - Gunakan Shift + Enter untuk baris baru
            </p>
            <Button
              type="submit"
              size="icon"
              className="rounded-full"
              disabled={sending || !input.trim()}
            >
              {sending ? (
                <Loader2Icon className="size-4 animate-spin" />
              ) : (
                <SendIcon className="size-4" />
              )}
            </Button>
          </div>
        </form>
        <p className="mt-3 text-center text-xs text-muted-foreground">
          OpenManus dapat saja menghasilkan kesalahan. Selalu tinjau kembali informasi penting.
        </p>
      </div>
    </div>
  );
}

