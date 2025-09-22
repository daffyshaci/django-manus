"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { useRestFetch } from "@/lib/client/useRestFetch";
import { useConversationWS } from "@/lib/client/ws";
import { FragmentProvider, useFragment } from "@/contexts/FragmentContext";
import { Fragment } from "@/components/Fragment";
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

import { Button } from "@/components/ui/button";
import { Image } from "@/components/ai-elements/image";
import { ThinkingAnimation } from "@/components/ai-elements/thinking-animation";

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

// Minimal ToolCall shape expected from backend/LLM for assistant tool_calls
// We keep fields optional to be resilient to backend differences
export type ToolCall = {
  id?: string;
  name?: string;
  tool_name?: string;
  type?: string;
  arguments?: unknown;
  args?: unknown;
};
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

// Normalize tool_calls of assistant message into typed array
function normalizeToolCalls(toolCalls: MessageSchema["tool_calls"]): ToolCall[] {
  if (!Array.isArray(toolCalls)) return [];
  return toolCalls.map((tc) => tc as unknown as ToolCall);
}

function getToolName(tc: ToolCall): string {
  // Try to get name from function.name first (most common case)
  const functionName = (tc as any)?.function?.name;
  if (functionName) return functionName.toString();

  // Fallback to other possible name fields
  const name = (tc.name || tc.tool_name || "").toString();
  return name || "unknown";
}

function pretty(value: unknown): string {
  try {
    return typeof value === "string" ? value : JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? "");
  }
}

function hasNonEmptyText(text: unknown): boolean {
  return typeof text === "string" && text.trim().length > 0;
}

function tryParseJSON<T = unknown>(text: string | null | undefined): T | string | null {
  if (!text) return text ?? null;
  try {
    return JSON.parse(text) as T;
  } catch {
    return text;
  }
}

// Build a lookup of tool result messages keyed by tool_call_id
// so we can attach ToolOutput to corresponding ToolInput
// This is recomputed when messages change
const toolResultByCallIdSelector = (messages: MessageSchema[]) => {
  const map = new Map<string, MessageSchema>();
  for (const m of messages) {
    if (m.role === "tool" && m.tool_call_id && !map.has(m.tool_call_id)) {
      map.set(m.tool_call_id, m);
    }
  }
  return map;
};

// Collect assistant tool_call ids to avoid rendering duplicate standalone tool messages
const assistantToolCallIdsSelector = (messages: MessageSchema[]) => {
  const set = new Set<string>();
  for (const m of messages) {
    if (m.role === "assistant" && Array.isArray(m.tool_calls)) {
      for (const tc of m.tool_calls) {
        const id = (tc as any)?.id;
        if (id) set.add(String(id));
      }
    }
  }
  return set;
};
const models = [
    { id: 'gpt-4o', name: 'GPT-4o' },
    { id: 'claude-opus-4-20250514', name: 'Claude 4 Opus' },
  ];

function ConversationPageContent() {
  const params = useParams();
  const router = useRouter();
  const { isSignedIn, userId, getToken } = useAuth();
  const { openFragment } = useFragment();
  const conversationId = useMemo(() => {
    const raw = params?.["conversation_id"];
    return Array.isArray(raw) ? raw[0] : (raw as string);
  }, [params]);

  const { restFetch } = useRestFetch({
    getToken: async () => (await getToken?.({ template: "manus" })) ?? (await getToken?.()) ?? null,
  });

  const [model, setModel] = useState(models[0].id);

  const [conversation, setConversation] = useState<ConversationSchema | null>(null);
  const [messages, setMessages] = useState<MessageSchema[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);
  const [thinkingText, setThinkingText] = useState<string | null>(null);

  type FileArtifactSchema = {
    id: string;
    path: string;
    filename: string;
    size_bytes: number;
    sha256: string;
    mime_type: string;
    stored_content: string;
    created_at?: string | null;
    updated_at?: string | null;
  };

  type TreeNode = { name: string; path: string; children?: TreeNode[]; file?: FileArtifactSchema };
  const [files, setFiles] = useState<FileArtifactSchema[]>([]);
  const [fileTree, setFileTree] = useState<TreeNode[]>([]);
  const [selectedFile, setSelectedFile] = useState<FileArtifactSchema | null>(null);
  const [selectedContent, setSelectedContent] = useState<string>("");

  const THINKING_ID = "__thinking__";
  function upsertThinking(show: boolean, text: string = "Agent thinking...") {
    if (!conversationId) return;
    if (show) {
      setThinkingText(text);
    } else {
      setThinkingText(null);
    }
  }

  const buildFileTree = useCallback((artifacts: FileArtifactSchema[]): TreeNode[] => {
    const root: Record<string, TreeNode> = {};
    for (const f of artifacts) {
      const parts = (f.path || f.filename).split("/").filter(Boolean);
      let curMap = root;
      let curPath = "";
      for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        curPath = curPath ? `${curPath}/${part}` : part;
        if (!curMap[part]) curMap[part] = { name: part, path: curPath, children: [] };
        if (i === parts.length - 1) curMap[part].file = f;
        if (curMap[part].children) {
          const nextMap: Record<string, TreeNode> = {};
          for (const child of curMap[part].children!) nextMap[child.name] = child;
          curMap = nextMap;
          curMap[part] = curMap[part] || { name: part, path: curPath, children: [] };
        }
      }
    }
    const toArray = (map: Record<string, TreeNode>): TreeNode[] => {
      const arr = Object.values(map);
      for (const node of arr) if (node.children && node.children.length) node.children = toArray(Object.fromEntries(node.children.map(c => [c.name, c])));
      return arr.sort((a, b) => a.name.localeCompare(b.name));
    };
    return toArray(root);
  }, []);

  const fetchFiles = useCallback(async () => {
    if (!conversationId) return;
    try {
      const data = await restFetch<FileArtifactSchema[]>(`/v1/chat/conversations/${conversationId}/files`);
      setFiles(data || []);
    } catch {}
  }, [conversationId, restFetch]);

  useEffect(() => {
    if (!files) return;
    const tree = buildFileTree(files);
    setFileTree(tree);
    if (selectedFile) {
      const match = files.find(f => f.id === selectedFile.id);
      if (match) setSelectedContent(match.stored_content || "");
    }
  }, [files, buildFileTree]);

  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  // ... existing code ...
  useConversationWS({
    conversationId: conversationId || "",
    getToken: async () => (await getToken?.({ template: "manus" })) ?? (await getToken?.()) ?? null,
    onMessage: (data) => {

      const eventName =
        data && typeof data === "object" && typeof (data as any).event === "string"
          ? ((data as any).event as string)
          : undefined;

      if (eventName === "agent.thoughts.start" || eventName === "agent.tools_prepared") {
        setAgentBusy(true);
        upsertThinking(true);
      }
      if (eventName === "agent.finished") {
        setAgentBusy(false);
        upsertThinking(false);
        fetchFiles();
      }

      const msg = extractMessageFromWS(data);
      if (msg && msg.conversation_id === conversationId) {
        const hasTerminateTool = msg.tool_calls && Array.isArray(msg.tool_calls) &&
          msg.tool_calls.some((tc: any) => {
            const toolName = tc?.function?.name || tc?.name || tc?.tool_name;
            return toolName === 'terminate';
          });

        setMessages((prev) => {
          if (prev.some((m) => m.id === msg.id)) return prev;
          let next = [...prev];
          if (msg.role === "user") {
            next = next.filter((m) => !m.id.startsWith("temp-") || m.role !== "user");
          }
          next.push(msg);
          next.sort((a, b) => {
            const ta = a.created_at ? Date.parse(a.created_at) : 0;
            const tb = b.created_at ? Date.parse(b.created_at) : 0;
            return ta - tb;
          });
          return next;
        });

        if (Array.isArray(msg.tool_calls)) {
          for (const tc of msg.tool_calls as any[]) {
            const tname = tc?.function?.name || tc?.name || tc?.tool_name;
            if (tname === 'file_editor') {
              const args = tc?.arguments ?? tc?.args;
              const parsedArgs = typeof args === 'string' ? tryParseJSON(args) : args;
              if (parsedArgs?.file_text) {
                const fileName = parsedArgs.path || 'file.txt';
                const fileExtension = fileName.split('.').pop() || 'txt';
                openFragment({
                  id: tc?.id || `${msg.id}-tc-fe`,
                  title: fileName,
                  content: parsedArgs.file_text,
                  language: getLanguageFromExtension(fileExtension),
                  path: parsedArgs.path,
                });
                setSelectedFile({
                  id: tc?.id || `${msg.id}-tc-fe`,
                  path: parsedArgs.path || fileName,
                  filename: fileName,
                  size_bytes: 0,
                  sha256: "",
                  mime_type: "text/plain",
                  stored_content: parsedArgs.file_text,
                });
                setSelectedContent(parsedArgs.file_text);
                fetchFiles();
              }
            }
          }
        }

        if (hasTerminateTool) {
          setAgentBusy(false);
          upsertThinking(false);
        }
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
      upsertThinking(true, "Agent thinking...");

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

  if (loading) {
    return (
      <div className="flex h-[600px] items-center justify-center">
        <Loader />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-[600px] items-center justify-center">
        <div className="text-center">
          <p className="text-red-500 mb-2">Error loading conversation</p>
          <p className="text-sm text-gray-600">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[600px]">
      {/* Chat Section */}
      <div className="flex-1 max-w-4xl mx-auto p-6">
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
              (() => {
                const toolResults = toolResultByCallIdSelector(messages);
                const assistantToolCallIds = assistantToolCallIdsSelector(messages);
                return (
                  <>
                    {messages.map((message) => {
                      if (message.role === 'tool') {
                        return null;
                      }

                      const from = (message.role === 'user' || message.role === 'assistant') ? message.role : 'assistant';

                      const toolCalls = normalizeToolCalls(message.tool_calls);
                      const hasToolCalls = toolCalls.length > 0 && message.role === 'assistant';
                      const hasText = hasNonEmptyText(message.content);
                      const hasImage = !!message.base64_image;

                      if (!hasToolCalls && !hasText && !hasImage) {
                        return null;
                      }

                      return (
                        <div key={message.id}>
                          {(hasText || hasImage) && (
                            <AiMessage from={from}>
                              <MessageContent variant="flat">
                                {hasText ? (
                                  <Response>
                                    {message.content as string}
                                  </Response>
                                ) : null}
                                {hasImage ? (
                                  <div className="mt-2">
                                    <Image
                                      base64={message.base64_image as string}
                                      uint8Array={new Uint8Array(0)}
                                      mediaType="image/png"
                                      alt="attachment"
                                    />
                                  </div>
                                ) : null}
                              </MessageContent>
                            </AiMessage>
                          )}

                          {hasToolCalls && (
                            <div className="space-y-2">
                              {toolCalls.map((tc, idx) => {
                                const callId = (tc as any)?.id ?? null;
                                const toolName = getToolName(tc);
                                if (toolName === 'terminate') return null;
                                const outputMsg = callId && toolResults.get(String(callId));

                                const handleFragmentClick = () => {
                                  if (toolName === 'file_editor') {
                                    const args = (tc as any)?.arguments ?? (tc as any)?.args;
                                    const parsedArgs = typeof args === 'string' ? tryParseJSON(args) : args;
                                    if (parsedArgs?.file_text) {
                                      const fileName = parsedArgs.path || 'file.txt';
                                      const fileExtension = fileName.split('.').pop() || 'txt';
                                      openFragment({
                                        id: callId || `${message.id}-tc-${idx}`,
                                        title: fileName,
                                        content: parsedArgs.file_text,
                                        language: getLanguageFromExtension(fileExtension),
                                        path: parsedArgs.path,
                                      });
                                      setSelectedFile({
                                        id: callId || `${message.id}-tc-${idx}`,
                                        path: parsedArgs.path || fileName,
                                        filename: fileName,
                                        size_bytes: 0,
                                        sha256: "",
                                        mime_type: "text/plain",
                                        stored_content: parsedArgs.file_text,
                                      });
                                      setSelectedContent(parsedArgs.file_text);
                                      fetchFiles();
                                    }
                                  }
                                };

                                return (
                                  <ToolCallUI key={callId || `${message.id}-${idx}`}
                                    toolName={toolName}
                                    callId={callId}
                                    outputMessage={outputMsg}
                                    onOpenFragment={handleFragmentClick}
                                  />
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })}
                    {agentBusy && thinkingText ? (
                      <AiMessage key={THINKING_ID} from="assistant">
                        <MessageContent>
                          <ThinkingAnimation variant="dots" size="md" />
                        </MessageContent>
                      </AiMessage>
                    ) : null}
                  </>
                );
              })()
            )}
          </ConversationContent>
          </Conversation>
        </div>
      </div>

      <div className="w-[600px] border-l p-4 flex flex-col">
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-medium">Sandbox Files</div>
          <button className="text-xs underline" onClick={() => fetchFiles()}>Refresh</button>
        </div>
        <div className="flex min-h-0 flex-1 gap-3">
          <div className="w-1/2 overflow-auto border rounded p-2">
            {fileTree.length ? renderTree(fileTree) : <div className="text-xs text-muted-foreground">No files</div>}
          </div>
          <div className="w-1/2 overflow-auto border rounded p-2">
            {selectedFile ? (
              <div>
                <div className="text-sm font-semibold mb-2">{selectedFile.filename}</div>
                <pre className="whitespace-pre-wrap text-xs">{selectedContent}</pre>
              </div>
            ) : (
              <div className="text-xs text-muted-foreground">Select a file to view</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// Helper function to get language from file extension
function getLanguageFromExtension(extension: string): string {
  const languageMap: Record<string, string> = {
    'js': 'javascript',
    'jsx': 'javascript',
    'ts': 'typescript',
    'tsx': 'typescript',
    'py': 'python',
    'html': 'html',
    'css': 'css',
    'json': 'json',
    'md': 'markdown',
    'yml': 'yaml',
    'yaml': 'yaml',
    'xml': 'xml',
    'sql': 'sql',
    'sh': 'bash',
    'bash': 'bash',
  };
  return languageMap[extension.toLowerCase()] || 'text';
}

export default function ConversationPage() {
  return (
    <FragmentProvider>
      <ConversationPageContent />
      <Fragment />
    </FragmentProvider>
  );
}
