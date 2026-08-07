import { useCallback, useEffect, useState } from "react";
import { BookOpenText, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import type { ParticipantContext, SessionSnapshot } from "../api/types";
import { BrowserLiveView } from "./BrowserLiveView";
import { GuidancePanel } from "./GuidancePanel";
import { useSessionEvents } from "./useSessionEvents";

interface ParticipantSessionProps {
  participant: ParticipantContext;
  initial: SessionSnapshot;
  initialLiveViewUrl?: string;
  onExit: () => void;
}

export function ParticipantSession({ participant, initial, initialLiveViewUrl, onExit }: ParticipantSessionProps) {
  const { snapshot, transport, error: connectionError, caregiverNote, refresh, applySnapshot } = useSessionEvents(initial.id, initial);
  const [liveViewUrl, setLiveViewUrl] = useState(initialLiveViewUrl ?? initial.liveViewUrl);
  const [liveViewLoading, setLiveViewLoading] = useState(!liveViewUrl);
  const [liveViewError, setLiveViewError] = useState<string>();
  const [voiceEnabled, setVoiceEnabled] = useState(participant.voiceEnabled);

  const loadLiveView = useCallback(async () => {
    setLiveViewLoading(true);
    setLiveViewError(undefined);
    try {
      setLiveViewUrl(await api.liveView(initial.id));
    } catch (reason) {
      setLiveViewError(reason instanceof Error ? reason.message : "Live View could not be loaded.");
    } finally {
      setLiveViewLoading(false);
    }
  }, [initial.id]);

  useEffect(() => {
    if (!liveViewUrl) void loadLiveView();
  }, [liveViewUrl, loadLiveView]);

  useEffect(() => {
    if (snapshot?.liveViewUrl && snapshot.liveViewUrl !== liveViewUrl) setLiveViewUrl(snapshot.liveViewUrl);
  }, [liveViewUrl, snapshot?.liveViewUrl]);

  if (!snapshot) {
    return (
      <main className="session-loading" id="main-content" role="status">
        <span className="large-spinner" />
        <h1>Connecting your task</h1>
      </main>
    );
  }

  const stop = async () => {
    try {
      await api.endTask(snapshot.id, "participant_stop");
    } finally {
      await api.stopBrowser(snapshot.id, "participant_stop");
      onExit();
    }
  };

  const retry = async () => {
    try {
      const attached = await api.attachBrowser(snapshot.id);
      applySnapshot({ ...snapshot, ...attached, id: snapshot.id });
      await loadLiveView();
    } catch {
      await refresh();
    }
  };

  return (
    <main className="session-page" id="main-content">
      <div className="session-context-bar">
        <div>
          <span className="session-context-bar__icon"><BookOpenText aria-hidden="true" size={20} /></span>
          <div>
            <span>Current task</span>
            <strong>{snapshot.task?.name ?? "Guided browsing"}</strong>
          </div>
        </div>
        <div className="session-context-bar__trust"><ShieldCheck aria-hidden="true" size={19} /> You stay in control</div>
      </div>
      <div className="session-layout">
        <BrowserLiveView
          error={liveViewError ?? (snapshot.phase === "provider_unavailable" ? snapshot.providerMessage : undefined)}
          liveViewUrl={liveViewUrl}
          loading={liveViewLoading}
          onRetry={() => void retry()}
          taskName={snapshot.task?.name}
        />
        <GuidancePanel
          connectionError={connectionError}
          caregiverNote={caregiverNote}
          onDismiss={async () => applySnapshot(await api.dismissHelp(snapshot))}
          onHelp={async () => applySnapshot(await api.requestHelp(snapshot))}
          onRetry={retry}
          onReturn={onExit}
          onStop={stop}
          onVoiceChange={setVoiceEnabled}
          snapshot={snapshot}
          transport={transport}
          voiceEnabled={voiceEnabled}
        />
      </div>
    </main>
  );
}
