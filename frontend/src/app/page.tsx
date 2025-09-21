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
          body: JSON.stringify({ model: "qwen3-32b", content: text }),
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
    <SidebarProvider>
      <div className="flex min-h-screen bg-background">
        <Sidebar collapsible="icon" className="border-r bg-background">
          <SidebarHeader className="border-b px-3 py-4">
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  size="lg"
                  className="justify-start gap-3 text-base font-semibold"
                  onClick={() => router.push("/")}
                >
                  <span className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <SparklesIcon className="size-5" />
                  </span>
                  <span className="flex-1 truncate">OpenManus</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton
                  variant="outline"
                  className="justify-start gap-3"
                  onClick={handleStartNewChat}
                >
                  <PlusIcon className="size-4" />
                  <span>Percakapan baru</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarHeader>
          <SidebarContent className="gap-6 px-2 py-4">
            <SidebarGroup>
              <SidebarGroupLabel>Percakapan</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      disabled
                      className="justify-start gap-3 text-muted-foreground"
                    >
                      <HistoryIcon className="size-4" />
                      <span>Riwayat akan muncul di sini</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
            <SidebarSeparator />
            <SidebarGroup>
              <SidebarGroupLabel>Prompt cepat</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {suggestions.map(({ title, icon: Icon }) => (
                    <SidebarMenuItem key={title}>
                      <SidebarMenuButton
                        className="justify-start gap-3"
                        onClick={() => handleSuggestionClick(title)}
                      >
                        <Icon className="size-4" />
                        <span className="truncate">{title}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
          <SidebarFooter className="border-t px-3 py-4">
            <SidebarMenu className="gap-2">
              <SidebarMenuItem>
                <SidebarMenuButton className="justify-start gap-3 text-sm" disabled>
                  <SettingsIcon className="size-4" />
                  Pengaturan
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton className="justify-start gap-3 text-sm" disabled>
                  <LifeBuoyIcon className="size-4" />
                  Bantuan & umpan balik
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
            <div className="mt-3 flex items-center justify-between rounded-lg border border-dashed px-3 py-2 text-xs text-muted-foreground">
              <span>Beta akses</span>
              <Badge variant="secondary">v0.1</Badge>
            </div>
          </SidebarFooter>
          <SidebarRail />
        </Sidebar>
        <SidebarInset className="bg-gradient-to-b from-background via-background to-muted/40">
          <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
            <div className="flex h-16 items-center gap-3 px-6">
              <SidebarTrigger className="md:hidden" />
              <div className="flex flex-1 items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <SparklesIcon className="size-5" />
                  </span>
                  <div className="space-y-1">
                    <p className="text-sm font-semibold tracking-tight">OpenManus Assistant</p>
                    <p className="text-xs text-muted-foreground">
                      Mulai percakapan baru dan lanjutkan pekerjaan Anda.
                    </p>
                  </div>
                </div>
                <Badge variant="secondary">Beta</Badge>
              </div>
            </div>
          </header>
          <div className="flex flex-1 flex-col overflow-hidden">
            <main className="flex-1 overflow-y-auto">
              <div className="mx-auto flex w-full max-w-4xl flex-col gap-10 px-6 pb-28 pt-12">
                <div className="text-center">
                  <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
                    Ada yang bisa saya bantu hari ini?
                  </h1>
                  <p className="mt-3 text-sm text-muted-foreground sm:text-base">
                    Gunakan saran di bawah atau ajukan pertanyaan Anda sendiri seputar naskah dan dokumen.
                  </p>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {suggestions.map(({ title, description, icon: Icon }) => (
                    <Card
                      key={title}
                      className="border-border/60 bg-muted/30 transition-colors hover:border-border hover:bg-muted/50"
                    >
                      <CardHeader className="space-y-3">
                        <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                          <Icon className="size-4" />
                          Rekomendasi prompt
                        </div>
                        <CardTitle className="text-lg">{title}</CardTitle>
                        <CardDescription>{description}</CardDescription>
                      </CardHeader>
                      <CardFooter className="px-6 pb-6 pt-0">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="ml-auto text-xs font-medium"
                          onClick={() => handleSuggestionClick(title)}
                        >
                          Gunakan prompt
                        </Button>
                      </CardFooter>
                    </Card>
                  ))}
                </div>
                <Card className="border-dashed bg-background/70">
                  <CardContent className="p-0">
                    <ScrollArea className="h-full">
                      <div className="flex h-full min-h-[280px] flex-col items-center justify-center gap-3 px-8 py-16 text-center">
                        <SparklesIcon className="size-8 text-muted-foreground/70" />
                        <h2 className="text-xl font-semibold">Mulai percakapan</h2>
                        <p className="text-sm text-muted-foreground">
                          Tulis pesan pertama Anda dan dapatkan respons terstruktur dari OpenManus.
                        </p>
                      </div>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </div>
            </main>
            <footer className="border-t bg-gradient-to-t from-background via-background/95 to-background/80 px-6 py-6 backdrop-blur supports-[backdrop-filter]:bg-background/80">
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
                  <div className="flex items-center justify-between gap-4 border-t px-5 pb-5 pt-3">
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
            </footer>
          </div>
        </SidebarInset>
      </div>
    </SidebarProvider>
  );
}

