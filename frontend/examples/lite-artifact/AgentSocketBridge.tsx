"use client";

import React from "react";
import { useAgentSocket } from "./useAgentSocket";

export function AgentSocketBridge() {
  const url = process.env.NEXT_PUBLIC_AGENT_WS_URL || "ws://localhost:8000/ws/agent/";
  useAgentSocket(url);
  return null;
}