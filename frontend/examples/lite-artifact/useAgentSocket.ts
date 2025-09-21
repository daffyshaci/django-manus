"use client";

import { useEffect, useRef } from "react";
import { useLiteArtifact } from "./ArtifactProvider";

export type AgentEvent =
  | {
      type: "agent.create_file:init";
      payload: { id: string; title?: string; mime?: string; content?: string; meta?: Record<string, unknown> };
    }
  | { type: "agent.create_file:chunk"; payload: { content: string } }
  | { type: "agent.create_file:finish"; payload?: { content?: string } }
  | { type: "agent.create_file:clear"; payload?: Record<string, never> }
  | { type: "error"; payload: { message: string } };

export function useAgentSocket(url: string) {
  const { actions } = useLiteArtifact();
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let isUnmounted = false;

    function connect() {
      if (wsRef.current) return;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        // Optionally send a hello message
      };

      ws.onmessage = (ev) => {
        try {
          const msg: AgentEvent = JSON.parse(ev.data);
          switch (msg.type) {
            case "agent.create_file:init":
              actions.init(msg.payload);
              break;
            case "agent.create_file:chunk":
              actions.chunk(msg.payload.content);
              break;
            case "agent.create_file:finish":
              actions.finish(msg.payload?.content);
              break;
            case "agent.create_file:clear":
              actions.clear();
              break;
            case "error":
              actions.setError(msg.payload.message);
              break;
            default:
              // ignore unknown
              break;
          }
        } catch (e) {
          actions.setError(`Invalid message: ${String(e)}`);
        }
      };

      ws.onerror = () => {
        actions.setError("WebSocket error");
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (!isUnmounted) {
          setTimeout(connect, 1500);
        }
      };
    }

    connect();

    return () => {
      isUnmounted = true;
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [url, actions]);
}