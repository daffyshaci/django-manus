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
  MessageContent,
} from "@/components/ai-elements/message";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolOutput,
  ToolInput,
} from '@/components/ai-elements/tool';
import {
  PromptInput,
  PromptInputActionAddAttachments,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuItem,
  PromptInputActionMenuTrigger,
  PromptInputAttachment,
  PromptInputAttachments,
  PromptInputBody,
  PromptInputButton,
  PromptInputModelSelect,
  PromptInputModelSelectContent,
  PromptInputModelSelectItem,
  PromptInputModelSelectTrigger,
  PromptInputModelSelectValue,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputToolbar,
  PromptInputTools,
  usePromptInputAttachments,
} from '@/components/ai-elements/prompt-input';
import { MessageSquare } from "lucide-react";
import { Loader } from "@/components/ai-elements/loader";
import { Response } from "@/components/ai-elements/response";
import { Task, TaskContent, TaskItem, TaskItemFile, TaskTrigger } from "@/components/ai-elements/task";
import { Button } from "@/components/ui/button";

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
  console.log(data)
  if (isMessageSchema(data)) return data;
  if (data && typeof data === "object") {
    const o = data as Record<string, unknown>;
    const payload = o.payload as unknown;

    if (typeof o.event === "string") {
      // Case A: { event, payload: Message }
      if (isMessageSchema(payload)) {
        console.log("out: ", payload)
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

const models = [
    { id: 'gpt-4o', name: 'GPT-4o' },
    { id: 'claude-opus-4-20250514', name: 'Claude 4 Opus' },
  ];

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

  const [model, setModel] = useState(models[0].id);

  const [conversation, setConversation] = useState<ConversationSchema | null>(null);
  const [messages, setMessages] = useState<MessageSchema[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);

  const THINKING_ID = "__thinking__";
  function upsertThinking(show: boolean, text: string = "Agent thinking...") {
    if (!conversationId) return;
    if (show) {
      setMessages((prev) => {
        if (prev.some((m) => m.id === THINKING_ID)) return prev;
        const temp: MessageSchema = {
          id: THINKING_ID,
          conversation_id: conversationId,
          role: "assistant",
          content: text,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        const next = [...prev, temp];
        next.sort((a, b) => {
          const ta = a.created_at ? Date.parse(a.created_at) : 0;
          const tb = b.created_at ? Date.parse(b.created_at) : 0;
          return ta - tb;
        });
        return next;
      });
    } else {
      setMessages((prev) => prev.filter((m) => m.id !== THINKING_ID));
    }
  }

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
        setMessages((detail.messages || []));
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

      const eventName =
        data && typeof data === "object" && typeof (data as any).event === "string"
          ? ((data as any).event as string)
          : undefined;

      if (eventName === "agent.thoughts.start" || eventName === "agent.tools_prepared" || eventName === "agent.tool_result") {
        setAgentBusy(true);
        upsertThinking(true);
      }
      if (eventName === "agent.finished") {
        setAgentBusy(false);
        upsertThinking(false);
      }

      const msg = extractMessageFromWS(data);
      if (msg && msg.conversation_id === conversationId) {
        // On real assistant/user message, replace thinking with actual content, then keep thinking if agent continues
        upsertThinking(false);
        setAgentBusy(true);
        setMessages((prev) => {
          // Avoid duplicates by id
          if (prev.some((m) => m.id === msg.id)) return prev;
          const next = [...prev, msg];
          next.sort((a, b) => {
            const ta = a.created_at ? Date.parse(a.created_at) : 0;
            const tb = b.created_at ? Date.parse(b.created_at) : 0;
            return ta - tb;
          });
          console.log(next)
          return next;
        });
        // Show thinking again until finished if backend continues processing
        upsertThinking(true);
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
      setAgentBusy(true);
      upsertThinking(true);

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
      setInput("");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    }
  }

  if (!isSignedIn) {
    return (
      // redirect login
      <div></div>
    );
  }

  if (!conversationId) {
    return (
      // redirect home
      <div></div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-6 h-[600px]">
      <div className="flex flex-col justify-between h-full">
        <Conversation>
          <ConversationContent>
            {messages.length === 0 ? (
              <ConversationEmptyState
                icon={<MessageSquare className="size-12" />}
                title="Start a conversation"
                description="Type a message below to begin chatting"
              />
            ) : (
              messages.map((message) => (
                <AiMessage from={message.role as 'system' | 'user' | 'assistant'} key={message.id}>
                  <MessageContent variant="flat">
                    <Response>
                      {message.id === THINKING_ID ? (
                        <Loader />
                      ) : (
                        message.content ?? ""
                      )}
                    </Response>
                  </MessageContent>
                </AiMessage>
              ))
            )}
            {/* Removed extra loader; thinking shown as a message */}
            <Task className="w-full">
              {/* <TaskTrigger title="Found project files" /> */}
              <TaskContent>
                <TaskItem>
                  Read <TaskItemFile
                    onClick={() => {
                      window.open('/chat/' + conversationId + '/index.md', '_blank');
                    }}
                  >
                      index.md
                  </TaskItemFile>
                </TaskItem>
              </TaskContent>
            </Task>
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>

        <PromptInput onSubmit={handlePromptSubmit} className="mt-4" globalDrop multiple>
          <PromptInputBody>
            <PromptInputAttachments>
              {(attachment) => <PromptInputAttachment data={attachment} />}
            </PromptInputAttachments>
            <PromptInputTextarea
              onChange={(e) => setInput(e.target.value)}
              value={input}
            />
          </PromptInputBody>
          <PromptInputToolbar>
            <PromptInputTools>
              <PromptInputActionMenu>
                <PromptInputActionMenuTrigger />
                <PromptInputActionMenuContent>
                  <PromptInputActionAddAttachments />
                </PromptInputActionMenuContent>
              </PromptInputActionMenu>
              <PromptInputModelSelect
                onValueChange={(value: string) => {
                  setModel(value);
                }}
                value={model}
              >
                <PromptInputModelSelectTrigger>
                  <PromptInputModelSelectValue />
                </PromptInputModelSelectTrigger>
                <PromptInputModelSelectContent>
                  {models.map((model) => (
                    <PromptInputModelSelectItem key={model.id} value={model.id}>
                      {model.name}
                    </PromptInputModelSelectItem>
                  ))}
                </PromptInputModelSelectContent>
              </PromptInputModelSelect>
            </PromptInputTools>
            <PromptInputSubmit disabled={!input && !loading} />
          </PromptInputToolbar>
        </PromptInput>
      </div>
    </div>
  )
}
