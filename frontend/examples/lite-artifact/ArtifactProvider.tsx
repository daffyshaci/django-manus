"use client";

import React, { createContext, useCallback, useContext, useMemo, useReducer } from "react";

export type LiteArtifact = {
  id: string;
  title?: string;
  mime?: string;
  content: string;
  meta?: Record<string, unknown>;
};

export type LiteArtifactStatus = "idle" | "init" | "streaming" | "done";

export type LiteArtifactState = {
  isVisible: boolean;
  status: LiteArtifactStatus;
  artifact: LiteArtifact | null;
  error?: string;
};

const initialState: LiteArtifactState = {
  isVisible: false,
  status: "idle",
  artifact: null,
};

type Action =
  | {
      type: "INIT";
      payload: {
        id: string;
        title?: string;
        mime?: string;
        content?: string;
        meta?: Record<string, unknown>;
      };
    }
  | { type: "CHUNK"; payload: { content: string } }
  | { type: "FINISH"; payload?: { content?: string } }
  | { type: "OPEN" }
  | { type: "CLOSE" }
  | { type: "CLEAR" }
  | { type: "ERROR"; payload: string };

function reducer(state: LiteArtifactState, action: Action): LiteArtifactState {
  switch (action.type) {
    case "INIT": {
      const { id, title, mime, content = "", meta } = action.payload;
      return {
        ...state,
        isVisible: true,
        status: "init",
        artifact: { id, title, mime, content, meta },
        error: undefined,
      };
    }
    case "CHUNK": {
      if (!state.artifact) return state;
      return {
        ...state,
        status: "streaming",
        artifact: { ...state.artifact, content: state.artifact.content + action.payload.content },
      };
    }
    case "FINISH": {
      if (!state.artifact) return state;
      const finalContent = action.payload?.content ?? state.artifact.content;
      return {
        ...state,
        status: "done",
        artifact: { ...state.artifact, content: finalContent },
      };
    }
    case "OPEN": {
      return { ...state, isVisible: true };
    }
    case "CLOSE": {
      return { ...state, isVisible: false };
    }
    case "CLEAR": {
      return { ...initialState };
    }
    case "ERROR": {
      return { ...state, error: action.payload };
    }
    default:
      return state;
  }
}

const LiteArtifactContext = createContext<{
  state: LiteArtifactState;
  actions: {
    init: (payload: { id: string; title?: string; mime?: string; content?: string; meta?: Record<string, unknown> }) => void;
    chunk: (content: string) => void;
    finish: (content?: string) => void;
    clear: () => void;
    open: () => void;
    close: () => void;
    setError: (msg: string) => void;
  };
} | null>(null);

export function LiteArtifactProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const init = useCallback(
    (payload: { id: string; title?: string; mime?: string; content?: string; meta?: Record<string, unknown> }) =>
      dispatch({ type: "INIT", payload }),
    []
  );
  const chunk = useCallback((content: string) => dispatch({ type: "CHUNK", payload: { content } }), []);
  const finish = useCallback((content?: string) => dispatch({ type: "FINISH", payload: content ? { content } : undefined }), []);
  const clear = useCallback(() => dispatch({ type: "CLEAR" }), []);
  const open = useCallback(() => dispatch({ type: "OPEN" }), []);
  const close = useCallback(() => dispatch({ type: "CLOSE" }), []);
  const setError = useCallback((msg: string) => dispatch({ type: "ERROR", payload: msg }), []);

  const value = useMemo(
    () => ({ state, actions: { init, chunk, finish, clear, open, close, setError } }),
    [state, init, chunk, finish, clear, open, close, setError]
  );

  return <LiteArtifactContext.Provider value={value}>{children}</LiteArtifactContext.Provider>;
}

export function useLiteArtifact() {
  const ctx = useContext(LiteArtifactContext);
  if (!ctx) throw new Error("useLiteArtifact must be used within LiteArtifactProvider");
  return ctx;
}