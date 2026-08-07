import { AlertTriangle, Check, CircleDot, Hand, Square, X } from "lucide-react";
import type { AgentRun, AgentStep } from "../api/types";

interface StepsPanelProps {
  run?: AgentRun;
  onConfirm: (approved: boolean) => void;
  onStop: () => void;
  busy: boolean;
}

const STATE_LABEL: Record<AgentRun["state"], string> = {
  running: "Working on it",
  needs_confirmation: "Waiting for you",
  completed: "All done",
  failed: "Stopped early",
  stopped: "Stopped",
};

/**
 * Shows what the agent has done, in the order it did it.
 *
 * Each line is the narration the planner wrote for a person, not a log line. The panel
 * reports; it never asks the participant to click something on the page.
 */
export function StepsPanel({ run, onConfirm, onStop, busy }: StepsPanelProps) {
  if (!run) {
    return (
      <aside aria-label="Activity" className="steps-panel">
        <header className="steps-panel__header">
          <h2>Activity</h2>
        </header>
        <p className="steps-panel__idle">Once a task starts, every step appears here in plain words.</p>
      </aside>
    );
  }

  const pause = run.pendingConfirmation;

  return (
    <aside aria-label="Activity" className="steps-panel">
      <header className="steps-panel__header">
        <div>
          <h2>{run.taskName}</h2>
          <p className={`steps-panel__state steps-panel__state--${run.state}`}>
            {run.state === "running" ? <span aria-hidden="true" className="spinner spinner--small" /> : null}
            {STATE_LABEL[run.state]}
          </p>
        </div>
        {run.state === "running" ? (
          <button className="button button--ghost button--small" disabled={busy} onClick={onStop} type="button">
            <Square aria-hidden="true" size={16} /> Stop
          </button>
        ) : null}
      </header>

      <ol aria-live="polite" className="steps-list">
        {run.steps.map((step) => (
          <li className={`step step--${step.status}`} key={`${step.stepNo}-${step.narration}`}>
            <span className="step__marker" aria-hidden="true">
              <StepIcon step={step} />
            </span>
            <div className="step__body">
              <p className="step__narration">{step.narration}</p>
              {step.detail ? <p className="step__detail">{step.detail}</p> : null}
            </div>
          </li>
        ))}
        {run.steps.length === 0 ? <li className="step step--running"><span className="step__marker"><span className="spinner spinner--small" /></span><div className="step__body"><p className="step__narration">Reading the page</p></div></li> : null}
      </ol>

      {pause ? (
        <div className="steps-panel__pause fade-in-up" role="alertdialog" aria-label="A decision is needed">
          <span className="steps-panel__pause-icon"><Hand aria-hidden="true" size={20} /></span>
          <p>{pause.message}</p>
          <div className="steps-panel__pause-actions">
            <button className="button button--primary" disabled={busy} onClick={() => onConfirm(true)} type="button">
              I&apos;ll take it from here
            </button>
            <button className="button button--secondary" disabled={busy} onClick={() => onConfirm(false)} type="button">
              <X aria-hidden="true" size={18} /> Stop here
            </button>
          </div>
        </div>
      ) : null}

      {run.summary && !pause ? (
        <p className={`steps-panel__summary steps-panel__summary--${run.state} fade-in-up`}>{run.summary}</p>
      ) : null}
    </aside>
  );
}

function StepIcon({ step }: { step: AgentStep }) {
  if (step.status === "done") return <Check size={15} />;
  if (step.status === "failed") return <AlertTriangle size={15} />;
  if (step.status === "blocked") return <Hand size={15} />;
  if (step.status === "running") return <span className="spinner spinner--small" />;
  return <CircleDot size={15} />;
}
