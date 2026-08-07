import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { api } from "../api/client";
import type { AgentRun } from "../api/types";
import { BrowserFrame } from "./BrowserFrame";
import { StepsPanel } from "./StepsPanel";

interface AgentDashboardProps {
  sessionId: string;
  taskName: string;
  initialRun?: AgentRun;
  onExit: () => void;
}

/**
 * The task dashboard: a browser on the left, what the agent did on the right.
 *
 * Run state arrives over the session stream, so steps appear as they happen. A slow poll
 * runs alongside it only so a dropped stream cannot leave the panel frozen.
 */
export function AgentDashboard({ sessionId, taskName, initialRun, onExit }: AgentDashboardProps) {
  const [run, setRun] = useState<AgentRun | undefined>(initialRun);
  const [liveViewUrl, setLiveViewUrl] = useState<string>();
  const [connecting, setConnecting] = useState(true);
  const [browserError, setBrowserError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const latestState = useRef(run?.state);

  latestState.current = run?.state;

  const loadLiveView = useCallback(async () => {
    setConnecting(true);
    setBrowserError(undefined);
    try {
      setLiveViewUrl(await api.liveView(sessionId));
    } catch (reason) {
      setBrowserError(reason instanceof Error ? reason.message : "The browser could not be reached.");
    } finally {
      setConnecting(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void loadLiveView();
  }, [loadLiveView]);

  useEffect(() => {
    const controller = new AbortController();
    let reconnect: number | undefined;
    const subscribe = () => {
      void api
        .streamAgentRun(sessionId, controller.signal, setRun)
        .catch(() => undefined)
        .finally(() => {
          if (controller.signal.aborted) return;
          if (latestState.current && latestState.current !== "running") return;
          reconnect = window.setTimeout(subscribe, 3_000);
        });
    };
    subscribe();
    return () => {
      controller.abort();
      if (reconnect !== undefined) window.clearTimeout(reconnect);
    };
  }, [sessionId]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (latestState.current && latestState.current !== "running") return;
      void api.agentRun(sessionId).then(setRun).catch(() => undefined);
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [sessionId]);

  const confirm = async (approved: boolean) => {
    setBusy(true);
    try {
      setRun(await api.confirmAgentRun(sessionId, approved));
    } catch {
      // The stream carries the authoritative state; a failed confirm will resurface there.
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    try {
      setRun(await api.stopAgentRun(sessionId));
    } catch {
      // Same as above: the run state is owned by the backend.
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="agent-dashboard page-enter" id="main-content">
      <header className="agent-dashboard__bar">
        <button className="text-button" onClick={onExit} type="button">
          <ArrowLeft aria-hidden="true" size={19} /> Tasks
        </button>
        <h1>{run?.taskName ?? taskName}</h1>
      </header>
      <div className="agent-dashboard__grid">
        <BrowserFrame
          connecting={connecting}
          error={browserError}
          liveViewUrl={liveViewUrl}
          onRetry={() => void loadLiveView()}
          run={run}
          taskName={taskName}
        />
        <StepsPanel busy={busy} onConfirm={(approved) => void confirm(approved)} onStop={() => void stop()} run={run} />
      </div>
    </main>
  );
}
