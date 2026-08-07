import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  Activity,
  ArrowLeft,
  BarChart3,
  BookOpenText,
  CheckCircle2,
  Clock3,
  DollarSign,
  Cloud,
  Database,
  FileCheck2,
  History,
  MessageSquareText,
  RefreshCw,
  Send,
  ShieldCheck,
  Upload,
  UserRound,
} from "lucide-react";
import { api } from "../api/client";
import type {
  CaregiverHistoryResponse,
  CaregiverNote,
  CaregiverSessionSummary,
  CostRunsResponse,
  ParticipantContext,
  ReadinessSnapshot,
  Routine,
} from "../api/types";
import { EmptyState } from "../shared/EmptyState";
import { participantUserId } from "../shared/participantIdentity";
import { SkillViewer } from "../skills/SkillViewer";

interface CaregiverViewProps {
  context?: ParticipantContext;
  onAuthenticated: (context: ParticipantContext) => void;
  onParticipant: () => void;
  onRefreshProviders: () => void;
  readiness?: ReadinessSnapshot;
  readinessError?: string;
  readinessLoading: boolean;
}

export function CaregiverView({
  context,
  onAuthenticated,
  onParticipant,
  onRefreshProviders,
  readiness,
  readinessError,
  readinessLoading,
}: CaregiverViewProps) {
  if (!context) return <CaregiverAccess onAuthenticated={onAuthenticated} onParticipant={onParticipant} />;
  return (
    <CaregiverDashboard
      context={context}
      onParticipant={onParticipant}
      onRefreshProviders={onRefreshProviders}
      readiness={readiness}
      readinessError={readinessError}
      readinessLoading={readinessLoading}
    />
  );
}

interface CaregiverAccessProps {
  onAuthenticated: (context: ParticipantContext) => void;
  onParticipant: () => void;
}

/**
 * Opens the caregiver console directly.
 *
 * There is no code to verify. The console reads the same activity the person on this
 * device already produced, so a shared secret added a step without adding protection.
 */
function CaregiverAccess({ onAuthenticated, onParticipant }: CaregiverAccessProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  const open = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      onAuthenticated(await api.createParticipantSession({
        user_id: participantUserId(),
        role: "caregiver",
        caregiver_name: "Caregiver",
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The caregiver console could not be opened.");
    } finally {
      setLoading(false);
    }
  }, [onAuthenticated]);

  useEffect(() => {
    void open();
  }, [open]);

  return (
    <main className="caregiver-access" id="main-content">
      <section className="caregiver-access__identity fade-in-up">
        <span className="section-kicker"><ShieldCheck aria-hidden="true" size={20} /> Caregiver console</span>
        <h1>{loading ? "Opening the console" : "See the record. Send one calm note."}</h1>
        <p>Every task, cost, and pause from this device, with nothing to sign in to.</p>
        {loading ? <div className="spinner spinner--large" role="status" aria-label="Opening the caregiver console" /> : null}
        {error ? (
          <>
            <p className="form-error" role="alert">{error}</p>
            <button className="button button--primary" onClick={() => void open()} type="button">Try again</button>
          </>
        ) : null}
        <button className="text-button" onClick={onParticipant} type="button"><ArrowLeft aria-hidden="true" size={19} /> Back to tasks</button>
      </section>
    </main>
  );
}

interface CaregiverDashboardProps {
  context: ParticipantContext;
  onParticipant: () => void;
  onRefreshProviders: () => void;
  readiness?: ReadinessSnapshot;
  readinessError?: string;
  readinessLoading: boolean;
}

function CaregiverDashboard({
  context,
  onParticipant,
  onRefreshProviders,
  readiness,
  readinessError,
  readinessLoading,
}: CaregiverDashboardProps) {
  const [history, setHistory] = useState<CaregiverHistoryResponse>();
  const [costs, setCosts] = useState<CostRunsResponse>();
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [historyError, setHistoryError] = useState<string>();
  const [costError, setCostError] = useState<string>();
  const [routineError, setRoutineError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [selectedSessionId, setSelectedSessionId] = useState<string>();
  const [selectedSkillId, setSelectedSkillId] = useState<string>();
  const [billFile, setBillFile] = useState<File>();
  const [billReviewed, setBillReviewed] = useState(false);
  const [uploadingBill, setUploadingBill] = useState(false);
  const [billUploadError, setBillUploadError] = useState<string>();
  const [billUploadStatus, setBillUploadStatus] = useState<string>();
  const billInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setHistoryError(undefined);
    setCostError(undefined);
    setRoutineError(undefined);
    const [dashboardResult, routineResult] = await Promise.allSettled([
      api.caregiverDashboard(),
      api.listRoutines(),
    ]);
    if (dashboardResult.status === "fulfilled") {
      setHistory(dashboardResult.value.history);
      setCosts(dashboardResult.value.costs);
      setCostError(dashboardResult.value.costError);
      setSelectedSessionId((current) => current ?? dashboardResult.value.history.sessions[0]?.id);
    } else {
      setHistory(undefined);
      setCosts(undefined);
      const message = dashboardResult.reason instanceof Error ? dashboardResult.reason.message : "Caregiver records are unavailable.";
      setHistoryError(message);
      setCostError(message);
    }
    if (routineResult.status === "fulfilled") setRoutines(routineResult.value);
    else {
      setRoutines([]);
      setRoutineError(routineResult.reason instanceof Error ? routineResult.reason.message : "Saved routines are unavailable.");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedSession = history?.sessions.find((session) => session.id === selectedSessionId);
  const completedCount = history?.sessions.filter((session) => session.outcome.toLowerCase() === "completed").length;
  const escalationCount = history?.sessions.filter((session) => Boolean(session.escalationId)).length;
  const verifiedSpend = costs?.runs.filter((run) => run.synced && run.costUsd !== undefined).reduce((sum, run) => sum + (run.costUsd ?? 0), 0);

  const uploadReviewedBill = async (event: FormEvent) => {
    event.preventDefault();
    if (!billFile || !billReviewed) return;
    setUploadingBill(true);
    setBillUploadError(undefined);
    setBillUploadStatus(undefined);
    try {
      const receipt = await api.uploadReviewedBill(billFile);
      setBillUploadStatus(
        receipt.indexingStatus === "awaiting_memory_add"
          ? "EverOS received the reviewed file. No bill facts have been added yet."
          : "EverOS received the reviewed file.",
      );
      setBillFile(undefined);
      setBillReviewed(false);
      if (billInput.current) billInput.current.value = "";
    } catch (reason) {
      setBillUploadError(
        reason instanceof Error ? reason.message : "EverOS could not upload the reviewed bill.",
      );
    } finally {
      setUploadingBill(false);
    }
  };

  return (
    <main className="caregiver-page" id="main-content">
      <header className="page-heading caregiver-heading">
        <div>
          <span className="eyebrow">Caregiver console</span>
          <h1>Welcome, {context.displayName}</h1>
          <p className="caregiver-heading__copy">A clear view of guidance, memory, and verified cloud records.</p>
        </div>
        <div className="heading-actions">
          <button className="button button--quiet" onClick={onParticipant} type="button"><ArrowLeft aria-hidden="true" size={19} /> Participant view</button>
          <button aria-label="Refresh caregiver records" className="icon-button" onClick={() => void load()} title="Refresh records" type="button"><RefreshCw aria-hidden="true" className={loading ? "spin" : undefined} size={22} /></button>
        </div>
      </header>

      <AgentStatusPanel
        error={readinessError}
        loading={readinessLoading}
        onRefresh={onRefreshProviders}
        readiness={readiness}
      />

      <section className="summary-strip" aria-label="Verified activity summary">
        <SummaryMetric icon={CheckCircle2} label="Completed tasks" unavailable={!history} value={completedCount} />
        <SummaryMetric icon={MessageSquareText} label="Help requests" unavailable={!history} value={escalationCount} />
        <SummaryMetric icon={DollarSign} label="Verified model cost" unavailable={!costs} value={verifiedSpend === undefined ? undefined : formatUsd(verifiedSpend)} />
      </section>

      <div className="caregiver-grid">
        <section className="caregiver-panel caregiver-history" aria-labelledby="history-title">
          <div className="section-heading-row">
            <div>
              <span className="section-kicker"><History aria-hidden="true" size={18} /> Session record</span>
              <h2 id="history-title">Recent activity</h2>
            </div>
          </div>
          {historyError ? <p className="inline-error" role="alert">{historyError}</p> : null}
          {!historyError && history?.sessions.length === 0 ? <EmptyState icon={History} message="No cloud session records were returned." title="No sessions yet" /> : null}
          <div className="history-list">
            {history?.sessions.map((session) => (
              <button
                aria-pressed={session.id === selectedSessionId}
                className={`history-row ${session.id === selectedSessionId ? "history-row--selected" : ""}`}
                key={session.id}
                onClick={() => setSelectedSessionId(session.id)}
                type="button"
              >
                <span className="history-row__mark" aria-hidden="true" />
                <span className="history-row__body"><strong>{session.taskName}</strong><small>{formatDateTime(session.startedAt)}</small></span>
                <span className={`outcome-label outcome-label--${session.outcome.toLowerCase()}`}>{humanize(session.outcome)}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="caregiver-panel session-detail" aria-labelledby="session-detail-title">
          <div className="section-heading-row">
            <div>
              <span className="section-kicker"><Clock3 aria-hidden="true" size={18} /> Selected session</span>
              <h2 id="session-detail-title">{selectedSession?.taskName ?? "Session details"}</h2>
            </div>
          </div>
          {selectedSession ? <SessionDetail context={context} session={selectedSession} /> : <EmptyState icon={Clock3} message="Choose a session to see its recorded status." title="No session selected" />}
        </section>
      </div>

      <section className="caregiver-panel cost-panel" aria-labelledby="cost-title">
        <div className="section-heading-row">
          <div>
            <span className="section-kicker"><BarChart3 aria-hidden="true" size={18} /> Snowflake record</span>
            <h2 id="cost-title">Cost by task run</h2>
          </div>
          {costs?.source ? <span className="data-source">{costs.source}</span> : null}
        </div>
        {costError ? <p className="inline-error" role="alert">{costError}</p> : null}
        {!costError && costs?.runs.length === 0 ? <EmptyState icon={BarChart3} message="No synchronized cost rows were returned." title="No verified cost data" /> : null}
        {costs && costs.runs.length > 0 ? <CostChart costs={costs} /> : null}
      </section>

      <section className="caregiver-panel reviewed-upload-panel" aria-labelledby="reviewed-upload-title">
        <div className="section-heading-row">
          <div>
            <span className="section-kicker"><FileCheck2 aria-hidden="true" size={18} /> EverOS reviewed input</span>
            <h2 id="reviewed-upload-title">Upload a reviewed bill</h2>
          </div>
        </div>
        <form className="reviewed-upload" onSubmit={uploadReviewedBill}>
          <label className="field" htmlFor="reviewed-bill-file">
            <span>PDF or bill image</span>
            <input
              accept=".pdf,image/jpeg,image/png,image/heic,image/heif"
              id="reviewed-bill-file"
              onChange={(event) => {
                setBillFile(event.target.files?.[0]);
                setBillReviewed(false);
                setBillUploadError(undefined);
                setBillUploadStatus(undefined);
              }}
              ref={billInput}
              type="file"
            />
          </label>
          <label className="reviewed-check">
            <input checked={billReviewed} disabled={!billFile} onChange={(event) => setBillReviewed(event.target.checked)} type="checkbox" />
            <span>I reviewed this file and want to upload it to EverOS.</span>
          </label>
          <button className="button button--primary" disabled={!billFile || !billReviewed || uploadingBill} type="submit"><Upload aria-hidden="true" size={19} /> {uploadingBill ? "Uploading" : "Upload reviewed bill"}</button>
          {billUploadError ? <p className="form-error" role="alert">{billUploadError}</p> : null}
          {billUploadStatus ? <p className="upload-confirmation" role="status"><CheckCircle2 aria-hidden="true" size={19} /> {billUploadStatus}</p> : null}
        </form>
      </section>

      <section className="caregiver-panel skill-index" aria-labelledby="skill-index-title">
        <div className="section-heading-row">
          <div>
            <span className="section-kicker"><BookOpenText aria-hidden="true" size={18} /> EverOS memory</span>
            <h2 id="skill-index-title">Readable routines</h2>
          </div>
        </div>
        {routineError ? <p className="inline-error" role="alert">{routineError}</p> : null}
        {!routineError && routines.length === 0 ? <EmptyState icon={BookOpenText} message="No saved skill documents were returned." title="No routines in memory" /> : null}
        <div className="skill-list">
          {routines.map((routine) => (
            <div className="skill-row" key={routine.id}>
              <div><strong>{routine.name}</strong><span>{routine.revision ? `Revision ${routine.revision}` : "Revision not reported"}</span></div>
              {routine.skillId ? <button className="button button--secondary" onClick={() => setSelectedSkillId(routine.skillId)} type="button"><BookOpenText aria-hidden="true" size={19} /> Read</button> : <span className="muted">Document unavailable</span>}
            </div>
          ))}
        </div>
      </section>

      {selectedSkillId ? (
        <SkillViewer
          editable
          onChanged={() => void load()}
          onClose={() => setSelectedSkillId(undefined)}
          onDeleted={() => {
            setSelectedSkillId(undefined);
            void load();
          }}
          skillId={selectedSkillId}
        />
      ) : null}
    </main>
  );
}

const agentServices = [
  {
    id: "browserbase",
    name: "Live browser",
    provider: "Browserbase",
    description: "Managed browser execution with a participant-visible Live View",
    icon: Cloud,
  },
  {
    id: "everos",
    name: "Memory",
    provider: "EverOS",
    description: "Routines, episodes, and participant context",
    icon: BookOpenText,
  },
  {
    id: "snowflake",
    name: "Verified records",
    provider: "Snowflake",
    description: "Session telemetry, cost, and reporting lineage",
    icon: Database,
  },
  {
    id: "guidance_model",
    name: "Guidance",
    provider: "Snowflake Cortex",
    description: "Live reasoning for unfamiliar or changed steps",
    icon: Activity,
  },
] as const;

function AgentStatusPanel({
  readiness,
  loading,
  error,
  onRefresh,
}: {
  readiness?: ReadinessSnapshot;
  loading: boolean;
  error?: string;
  onRefresh: () => void;
}) {
  const overallReady = Boolean(readiness?.ready) && !error;
  return (
    <section className="agent-status" aria-labelledby="agent-status-title">
      <div className="agent-status__heading">
        <div>
          <span className="section-kicker"><Activity aria-hidden="true" size={18} /> Live agent status</span>
          <h2 id="agent-status-title">Cloud connections</h2>
          <p>Keys stay on the server. This console shows only safe connection status.</p>
        </div>
        <div className="agent-status__overall">
          <span className={`agent-live-dot ${overallReady ? "agent-live-dot--ready" : ""}`} aria-hidden="true" />
          <strong>{loading ? "Checking" : overallReady ? "Agent ready" : "Needs attention"}</strong>
          <button aria-label="Refresh live agent status" className="icon-button icon-button--small" onClick={onRefresh} title="Refresh live agent status" type="button">
            <RefreshCw aria-hidden="true" className={loading ? "spin" : undefined} size={18} />
          </button>
        </div>
      </div>
      {error ? <p className="inline-error" role="alert">{error}</p> : null}
      <div className="agent-status__grid">
        {agentServices.map((service) => {
          const capability = readiness?.capabilities.find((item) => item.name === service.id);
          const ready = Boolean(capability?.configured && capability.reachable && capability.authorized);
          const status = loading && !capability ? "Checking" : ready ? "Connected" : capability?.configured ? "Attention" : "Unavailable";
          const Icon = service.icon;
          return (
            <article className={`agent-service ${ready ? "agent-service--ready" : ""}`} key={service.id}>
              <span className="agent-service__icon"><Icon aria-hidden="true" size={24} /></span>
              <div>
                <span>{service.name}</span>
                <strong>{service.provider}</strong>
                <small>{service.description}</small>
              </div>
              <span className={`agent-service__state ${ready ? "agent-service__state--ready" : ""}`}>
                {status}
              </span>
            </article>
          );
        })}
      </div>
      {readiness?.checkedAt ? <small className="agent-status__checked">Last checked {formatDateTime(readiness.checkedAt)}</small> : null}
    </section>
  );
}

interface SummaryMetricProps {
  icon: typeof CheckCircle2;
  label: string;
  value?: string | number;
  unavailable: boolean;
}

function SummaryMetric({ icon: Icon, label, value, unavailable }: SummaryMetricProps) {
  return (
    <div className="summary-metric">
      <span className="summary-metric__icon"><Icon aria-hidden="true" size={24} /></span>
      <div><span>{label}</span><strong>{unavailable ? "Unavailable" : value ?? 0}</strong></div>
    </div>
  );
}

function SessionDetail({ context, session }: { context: ParticipantContext; session: CaregiverSessionSummary }) {
  const [message, setMessage] = useState("");
  const [note, setNote] = useState<CaregiverNote>();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();

  useEffect(() => {
    setMessage("");
    setNote(undefined);
    setError(undefined);
  }, [session.id]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!session.escalationId || !message.trim()) return;
    setSending(true);
    setError(undefined);
    try {
      setNote(await api.addCaregiverNote(session.escalationId, message.trim(), context.displayName));
      setMessage("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The note could not be sent.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="session-detail__content">
      <dl className="detail-list">
        <div><dt>Participant</dt><dd>{session.participantName ?? "Not reported"}</dd></div>
        <div><dt>Started</dt><dd>{formatDateTime(session.startedAt)}</dd></div>
        <div><dt>Ended</dt><dd>{session.endedAt ? formatDateTime(session.endedAt) : "In progress"}</dd></div>
        <div><dt>Guidance</dt><dd>{session.guidanceMode ? humanize(session.guidanceMode) : "Not reported"}</dd></div>
        <div><dt>Outcome</dt><dd>{humanize(session.outcome)}</dd></div>
        <div><dt>Record</dt><dd>{session.syncState ? humanize(session.syncState) : "Not reported"}</dd></div>
      </dl>

      <form className="note-form" onSubmit={submit}>
        <label htmlFor={`note-${session.id}`}><MessageSquareText aria-hidden="true" size={19} /> Note to participant</label>
        <textarea
          disabled={!session.escalationId}
          id={`note-${session.id}`}
          maxLength={240}
          onChange={(event) => setMessage(event.target.value)}
          placeholder={session.escalationId ? "Write one short, calm message" : "Notes are available for help requests"}
          rows={3}
          value={message}
        />
        <div className="note-form__footer">
          <span>{message.length}/240</span>
          <button className="button button--primary" disabled={!session.escalationId || !message.trim() || sending} type="submit"><Send aria-hidden="true" size={19} /> {sending ? "Sending" : "Send note"}</button>
        </div>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        {note ? <p className="note-confirmation" role="status"><CheckCircle2 aria-hidden="true" size={19} /> Note saved{note.deliveryStatus ? ` · ${humanize(note.deliveryStatus)}` : ""}</p> : null}
      </form>
    </div>
  );
}

function CostChart({ costs }: { costs: CostRunsResponse }) {
  const measuredRuns = costs.runs.filter((run) => run.costUsd !== undefined);
  const maxCost = Math.max(...measuredRuns.map((run) => run.costUsd ?? 0), 0);
  return (
    <div className="cost-chart">
      <div className="cost-chart__rows">
        {costs.runs.map((run) => {
          const width = run.costUsd === undefined || maxCost === 0 ? 0 : Math.max(2, ((run.costUsd ?? 0) / maxCost) * 100);
          return (
            <div className="cost-row" key={run.runId}>
              <div className="cost-row__label"><strong>{run.taskName}</strong><span>{run.runNumber ? `Run ${run.runNumber}` : "Run"} · {humanize(run.mode)}</span></div>
              <div className="cost-track" aria-hidden="true"><span className={`cost-bar cost-bar--${run.mode}`} style={{ width: `${width}%` }} /></div>
              <div className="cost-row__value"><strong>{run.costUsd === undefined ? "Unavailable" : formatUsd(run.costUsd)}</strong><span>{run.synced ? "Synced" : "Not synced"}</span></div>
            </div>
          );
        })}
      </div>
      <div className="cost-table-wrap">
        <table>
          <thead><tr><th>Task</th><th>Mode</th><th>Tokens</th><th>Latency</th><th>Cost</th></tr></thead>
          <tbody>
            {costs.runs.map((run) => (
              <tr key={`${run.runId}-detail`}>
                <td>{run.taskName}</td>
                <td>{humanize(run.mode)}</td>
                <td>{run.totalTokens ?? (run.inputTokens === undefined && run.outputTokens === undefined ? "Unavailable" : (run.inputTokens ?? 0) + (run.outputTokens ?? 0))}</td>
                <td>{run.latencyMs === undefined ? "Unavailable" : `${(run.latencyMs / 1000).toFixed(1)} s`}</td>
                <td>{run.costUsd === undefined ? "Unavailable" : formatUsd(run.costUsd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatUsd(value: number): string {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(value);
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toLocaleUpperCase());
}
