import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  BadgeCheck,
  Ban,
  BellRing,
  CheckCircle2,
  CircleHelp,
  CloudOff,
  Eye,
  Hand,
  HeartHandshake,
  PauseCircle,
  RefreshCw,
  Route,
  Search,
  ShieldAlert,
  Sparkles,
  Square,
  Volume2,
  VolumeX,
  Wrench,
} from "lucide-react";
import type { CaregiverPanelNote, SessionSnapshot } from "../api/types";
import type { SessionTransport } from "./useSessionEvents";
import { phasePresentation } from "./state";
import { StatusBadge } from "../shared/StatusBadge";

interface GuidancePanelProps {
  snapshot: SessionSnapshot;
  transport: SessionTransport;
  connectionError?: string;
  caregiverNote?: CaregiverPanelNote;
  voiceEnabled: boolean;
  onVoiceChange: (enabled: boolean) => void;
  onHelp: () => Promise<void>;
  onDismiss: () => Promise<void>;
  onRetry: () => Promise<void>;
  onStop: () => Promise<void>;
  onReturn: () => void;
}

function formatAmount(snapshot: SessionSnapshot): string | undefined {
  const amount = snapshot.command?.safety?.amount ?? snapshot.amount;
  if (!amount) return undefined;
  const number = Number(amount.value);
  if (Number.isFinite(number) && amount.currency) {
    try {
      return new Intl.NumberFormat(undefined, { style: "currency", currency: amount.currency }).format(number);
    } catch {
      return `${amount.value} ${amount.currency}`;
    }
  }
  return amount.currency ? `${amount.value} ${amount.currency}` : amount.value;
}

export function GuidancePanel({
  snapshot,
  transport,
  connectionError,
  caregiverNote,
  voiceEnabled,
  onVoiceChange,
  onHelp,
  onDismiss,
  onRetry,
  onStop,
  onReturn,
}: GuidancePanelProps) {
  const [working, setWorking] = useState(false);
  const [actionError, setActionError] = useState<string>();
  const phase = phasePresentation[snapshot.phase];
  const instruction = snapshot.command?.instruction;
  const amount = formatAmount(snapshot);

  useEffect(() => {
    if (!voiceEnabled || !instruction || !(snapshot.phase === "guiding" || snapshot.phase === "awaiting_user_action")) return;
    window.speechSynthesis?.cancel();
    const utterance = new SpeechSynthesisUtterance(instruction);
    utterance.rate = 0.88;
    window.speechSynthesis?.speak(utterance);
    return () => window.speechSynthesis?.cancel();
  }, [instruction, snapshot.command?.id, snapshot.phase, voiceEnabled]);

  const run = async (action: () => Promise<void>) => {
    setWorking(true);
    setActionError(undefined);
    try {
      await action();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "That action could not be completed.");
    } finally {
      setWorking(false);
    }
  };

  const body = useMemo(() => {
    switch (snapshot.phase) {
      case "created":
        return <PanelMessage icon={Search} title="Opening your task" message="The browser and your saved routine are connecting." busy />;
      case "observing":
        return (
          <PanelMessage icon={Eye} title="You can continue" message="I’m watching quietly and will offer help if you get stuck.">
            <button className="button button--primary button--large" disabled={working} onClick={() => void run(onHelp)} type="button">
              <CircleHelp aria-hidden="true" size={23} /> Help me
            </button>
          </PanelMessage>
        );
      case "help_offered":
        return (
          <PanelMessage icon={HeartHandshake} title="Would you like a hand?" message={instruction ?? "I can show you the next step on this page."}>
            <div className="button-stack">
              <button className="button button--primary button--large" disabled={working} onClick={() => void run(onHelp)} type="button"><Sparkles aria-hidden="true" size={22} /> Show me</button>
              <button className="button button--quiet" disabled={working} onClick={() => void run(onDismiss)} type="button"><Ban aria-hidden="true" size={21} /> Not now</button>
            </div>
          </PanelMessage>
        );
      case "guiding":
      case "awaiting_user_action":
        return (
          <div className="instruction-state">
            <span className="instruction-number">Next step</span>
            <Hand aria-hidden="true" className="instruction-icon" size={34} />
            <p className="instruction-copy">{instruction ?? "The next instruction is not available yet."}</p>
            <p className="instruction-footnote">Use the real browser beside this panel.</p>
          </div>
        );
      case "verifying":
        return <PanelMessage icon={Search} title="Checking what changed" message="The next step will appear when the page matches." busy />;
      case "rerouting":
        return <PanelMessage icon={Route} title="That’s alright" message="I’m finding the next step from where you are now." busy />;
      case "repairing":
        return <PanelMessage icon={Wrench} title="This page has changed" message="I’m updating this one step, then your saved routine will continue." busy />;
      case "safety_paused": {
        const safety = snapshot.command?.safety;
        return (
          <PanelMessage
            icon={safety?.classification === "suspicious" ? ShieldAlert : PauseCircle}
            title={safety?.title ?? "Let’s pause a moment"}
            message={safety?.message ?? safety?.actionDescription ?? "This action needs your attention before anything happens."}
            tone="warning"
          >
            {amount ? <div className="amount-callout"><span>Amount</span><strong>{amount}</strong></div> : null}
            <p className="safety-note">Nothing has been submitted. Use the real site button only when you are ready.</p>
            <button className="button button--secondary" disabled={working} onClick={() => void run(onHelp)} type="button"><BellRing aria-hidden="true" size={21} /> Ask caregiver</button>
          </PanelMessage>
        );
      }
      case "escalated": {
        const delivered = snapshot.escalationDelivery === "delivered" || snapshot.escalationDelivery === "sent";
        return (
          <PanelMessage
            icon={HeartHandshake}
            title={delivered ? "Your caregiver has been notified" : "Your help request is saved"}
            message={delivered ? "You can wait here. This browser will not continue on its own." : "Delivery is still pending. This browser will not continue on its own."}
            tone="warning"
          >
            <button className="button button--secondary" onClick={onReturn} type="button">Return to routines</button>
          </PanelMessage>
        );
      }
      case "completed":
        return (
          <PanelMessage icon={BadgeCheck} title="This task is finished" message={snapshot.outcomeMessage ?? "The site confirmed that the task was completed."} tone="success">
            {amount ? <div className="amount-callout amount-callout--success"><span>Confirmed amount</span><strong>{amount}</strong></div> : null}
            <button className="button button--primary" onClick={onReturn} type="button"><CheckCircle2 aria-hidden="true" size={21} /> Done</button>
          </PanelMessage>
        );
      case "prepared":
        return (
          <PanelMessage icon={CheckCircle2} title="Ready for your confirmation" message={snapshot.outcomeMessage ?? "The task stopped before the final action, as planned."} tone="success">
            {amount ? <div className="amount-callout"><span>Prepared amount</span><strong>{amount}</strong></div> : null}
            <button className="button button--primary" onClick={onReturn} type="button">Return to routines</button>
          </PanelMessage>
        );
      case "provider_unavailable":
        return (
          <PanelMessage icon={CloudOff} title="The managed browser is unavailable" message={snapshot.providerMessage ?? snapshot.providerErrorCode ?? "Browserbase could not continue this session."} tone="danger">
            <button className="button button--secondary" disabled={working} onClick={() => void run(onRetry)} type="button"><RefreshCw aria-hidden="true" size={21} /> Try again</button>
          </PanelMessage>
        );
      case "failed":
        return (
          <PanelMessage icon={CloudOff} title="This task could not continue" message={snapshot.outcomeMessage ?? "The session stopped without completing the task."} tone="danger">
            <button className="button button--secondary" onClick={onReturn} type="button">Return to routines</button>
          </PanelMessage>
        );
      case "abandoned":
        return <PanelMessage icon={Square} title="This task was stopped" message={snapshot.outcomeMessage ?? "No completion was recorded."}><button className="button button--secondary" onClick={onReturn} type="button">Return to routines</button></PanelMessage>;
    }
  }, [amount, instruction, onDismiss, onHelp, onRetry, onReturn, snapshot, working]);

  const transportLabel = transport === "streaming" ? "Live updates" : transport === "polling" ? "Checking for updates" : transport === "offline" ? "Updates disconnected" : "Connecting updates";

  return (
    <aside className="guidance-panel" aria-label="WebAccessible guidance" aria-live="polite">
      <header className="guidance-panel__header">
        <StatusBadge busy={phase.busy} label={phase.label} tone={phase.tone} />
        <button
          aria-label={voiceEnabled ? "Turn voice off" : "Turn voice on"}
          aria-pressed={voiceEnabled}
          className="icon-button"
          onClick={() => onVoiceChange(!voiceEnabled)}
          title={voiceEnabled ? "Turn voice off" : "Turn voice on"}
          type="button"
        >
          {voiceEnabled ? <Volume2 aria-hidden="true" size={23} /> : <VolumeX aria-hidden="true" size={23} />}
        </button>
      </header>
      <div className="guidance-panel__body">
        {caregiverNote ? (
          <div className="caregiver-message" role="status">
            <HeartHandshake aria-hidden="true" size={22} />
            <div><strong>{caregiverNote.authorName}</strong><p>{caregiverNote.text}</p></div>
          </div>
        ) : null}
        {body}
        {actionError ? <p className="form-error guidance-action-error" role="alert">{actionError}</p> : null}
      </div>
      <footer className="guidance-panel__footer">
        <div className="session-health">
          <span className={`connection-light connection-light--${transport}`} aria-hidden="true" />
          <span>{connectionError ?? transportLabel}</span>
        </div>
        {snapshot.syncState ? <span className={`sync-label sync-label--${snapshot.syncState}`}>{snapshot.syncState === "synced" ? "Record synced" : snapshot.syncState === "sync_pending" ? "Record pending" : "Record sync failed"}</span> : null}
        {!(["completed", "prepared", "abandoned", "failed"] as string[]).includes(snapshot.phase) ? (
          <button className="text-button text-button--danger" disabled={working} onClick={() => void run(onStop)} type="button"><Square aria-hidden="true" size={17} /> Stop task</button>
        ) : null}
      </footer>
    </aside>
  );
}

interface PanelMessageProps {
  icon: typeof Search;
  title: string;
  message: string;
  tone?: "neutral" | "warning" | "danger" | "success";
  busy?: boolean;
  children?: ReactNode;
}

function PanelMessage({ icon: Icon, title, message, tone = "neutral", busy = false, children }: PanelMessageProps) {
  return (
    <div className={`panel-message panel-message--${tone}`}>
      <span className="panel-message__icon">{busy ? <span className="large-spinner" /> : <Icon aria-hidden="true" size={35} />}</span>
      <h2>{title}</h2>
      <p>{message}</p>
      {children ? <div className="panel-message__actions">{children}</div> : null}
    </div>
  );
}
