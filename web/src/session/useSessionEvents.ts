import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { CaregiverPanelNote, SessionSnapshot } from "../api/types";

export type SessionTransport = "connecting" | "streaming" | "polling" | "offline";

interface SessionEventsState {
  snapshot?: SessionSnapshot;
  transport: SessionTransport;
  error?: string;
  caregiverNote?: CaregiverPanelNote;
  refresh: () => Promise<void>;
  applySnapshot: (snapshot: SessionSnapshot) => void;
}

const POLL_INTERVAL_MS = 2500;

export function useSessionEvents(sessionId: string | undefined, initial?: SessionSnapshot): SessionEventsState {
  const [snapshot, setSnapshot] = useState<SessionSnapshot | undefined>(initial);
  const [transport, setTransport] = useState<SessionTransport>("connecting");
  const [error, setError] = useState<string>();
  const [caregiverNote, setCaregiverNote] = useState<CaregiverPanelNote>();
  const latestVersion = useRef(initial?.stateVersion ?? -1);

  const applySnapshot = useCallback((next: SessionSnapshot) => {
    if (next.stateVersion < latestVersion.current) {
      setError("An older session update was ignored.");
      return;
    }
    latestVersion.current = next.stateVersion;
    setSnapshot(next);
    setError(undefined);
  }, []);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try {
      applySnapshot(await api.getSession(sessionId));
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "The session could not be refreshed.";
      setError(message);
      throw reason;
    }
  }, [applySnapshot, sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    const streamController = new AbortController();
    let pollTimer: number | undefined;
    let disposed = false;

    const poll = async () => {
      if (disposed) return;
      try {
        const next = await api.getSession(sessionId);
        if (!disposed) {
          applySnapshot(next);
          setTransport("polling");
        }
      } catch (reason) {
        if (!disposed) {
          setTransport("offline");
          setError(reason instanceof Error ? reason.message : "The session connection was lost.");
        }
      } finally {
        if (!disposed) pollTimer = window.setTimeout(poll, POLL_INTERVAL_MS);
      }
    };

    const start = async () => {
      setTransport("connecting");
      try {
        applySnapshot(await api.getSession(sessionId));
      } catch (reason) {
        if (!disposed) setError(reason instanceof Error ? reason.message : "The session could not be loaded.");
      }
      if (disposed) return;
      try {
        setTransport("streaming");
        await api.streamSession(sessionId, streamController.signal, applySnapshot, setCaregiverNote);
        if (!disposed) void poll();
      } catch (reason) {
        if (disposed || streamController.signal.aborted) return;
        if (!(reason instanceof ApiError) || reason.code !== "stream_unavailable") {
          setError(reason instanceof Error ? reason.message : "Live updates were interrupted.");
        }
        void poll();
      }
    };

    void start();
    return () => {
      disposed = true;
      streamController.abort();
      if (pollTimer) window.clearTimeout(pollTimer);
    };
  }, [applySnapshot, sessionId]);

  return { snapshot, transport, error, caregiverNote, refresh, applySnapshot };
}
