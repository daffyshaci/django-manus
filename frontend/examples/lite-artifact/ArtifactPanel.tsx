"use client";

import React from "react";
import { useLiteArtifact } from "./ArtifactProvider";
import { AnimatePresence, motion } from "framer-motion";

export function ArtifactPanel() {
  const { state, actions } = useLiteArtifact();

  const visible = state.isVisible && !!state.artifact;
  const { title, content, mime } = state.artifact ?? {};

  return (
    <AnimatePresence>
      {visible && (
        <motion.aside
          key="artifact-panel"
          initial={{ x: "100%", opacity: 0.6 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: "100%", opacity: 0.6 }}
          transition={{ type: "tween", duration: 0.25, ease: "easeOut" }}
          style={{
            position: "fixed",
            top: 0,
            right: 0,
            height: "100vh",
            width: "48vw",
            borderLeft: "1px solid #eee",
            background: "#fff",
            display: "flex",
            flexDirection: "column",
            boxShadow: "-8px 0 16px rgba(0,0,0,0.05)",
            zIndex: 60,
          }}
          aria-label="Artifact panel"
        >
          <header style={{ padding: "12px 16px", borderBottom: "1px solid #eee", display: "flex", gap: 8, alignItems: "center" }}>
            <strong style={{ flex: 1 }}>{title ?? "Artifact"}</strong>
            <span style={{ fontSize: 12, color: "#666" }}>{state.status}</span>
            <button onClick={actions.close} style={{ marginLeft: 8, padding: "6px 10px", border: "1px solid #ddd", borderRadius: 6 }}>
              Close
            </button>
            <button onClick={actions.clear} style={{ marginLeft: 8, padding: "6px 10px", border: "1px solid #ddd", borderRadius: 6 }}>
              Reset
            </button>
          </header>

          <div style={{ padding: 16, overflow: "auto", flex: 1 }}>
            {mime?.startsWith("image/") ? (
              <img src={content as string} alt={title ?? "artifact"} style={{ maxWidth: "100%" }} />
            ) : mime === "text/html" ? (
              <iframe title="artifact-html" srcDoc={content as string} style={{ width: "100%", height: "100%", border: 0 }} />
            ) : (
              <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{content as string}</pre>
            )}
          </div>

          {state.error && (
            <div style={{ color: "#c00", borderTop: "1px solid #f3caca", background: "#fff5f5", padding: 12 }}>{state.error}</div>
          )}
        </motion.aside>
      )}
    </AnimatePresence>
  );
}