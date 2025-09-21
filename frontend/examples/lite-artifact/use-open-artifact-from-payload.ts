"use client";

import { useLiteArtifact } from "@/examples/lite-artifact/ArtifactProvider";

export type FilePayload = { path?: string; content?: string; file_name?: string };

export function guessMimeFromName(name?: string): string {
  if (!name) return "text/plain";
  const lower = name.toLowerCase();
  if (lower.endsWith(".md")) return "text/markdown";
  if (lower.endsWith(".json")) return "application/json";
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  if (lower.endsWith(".csv")) return "text/csv";
  if (lower.endsWith(".ts") || lower.endsWith(".tsx")) return "text/typescript";
  if (lower.endsWith(".js") || lower.endsWith(".jsx")) return "text/javascript";
  if (lower.endsWith(".py")) return "text/x-python";
  if (lower.endsWith(".html")) return "text/html";
  if (lower.endsWith(".css")) return "text/css";
  return "text/plain";
}

export function useOpenArtifactFromPayload() {
  const { actions } = useLiteArtifact();

  return (file: FilePayload) => {
    const id = file.path || file.file_name || "artifact";
    const title = file.file_name || file.path || "Artifact";
    const mime = guessMimeFromName(file.file_name || file.path);
    const content = file.content || "";

    actions.init({ id, title, mime, content });
  };
}