import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ArrowRight, BellRing, Check, CheckCircle2, CircleHelp, Clock3, Copy, HeartHandshake, RefreshCw, Search, Sparkles, X } from "lucide-react";
import { api } from "../api/client";
import type { EpisodeAnswer, ParticipantContext, ProactiveReminder, Routine } from "../api/types";
import { EmptyState } from "../shared/EmptyState";

interface RoutineChooserProps {
  participant: ParticipantContext;
  onStart: (routine: Routine) => Promise<void>;
  onStartReminder: (reminderId: string) => Promise<void>;
  starting: boolean;
  startError?: string;
}

export function RoutineChooser({ participant, onStart, onStartReminder, starting, startError }: RoutineChooserProps) {
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [resolving, setResolving] = useState(false);
  const [resolved, setResolved] = useState<Routine[]>();
  const [episodeQuery, setEpisodeQuery] = useState("");
  const [episode, setEpisode] = useState<EpisodeAnswer>();
  const [episodeLoading, setEpisodeLoading] = useState(false);
  const [episodeError, setEpisodeError] = useState<string>();
  const [codeCopied, setCodeCopied] = useState(false);
  const [reminders, setReminders] = useState<ProactiveReminder[]>([]);
  const [reminderError, setReminderError] = useState<string>();

  const loadRoutines = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      setRoutines(await api.listRoutines());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Saved routines could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRoutines();
  }, [loadRoutines]);

  const loadReminders = useCallback(async () => {
    setReminderError(undefined);
    try {
      setReminders(await api.listReminders());
    } catch (reason) {
      setReminderError(reason instanceof Error ? reason.message : "Suggestions could not be checked.");
    }
  }, []);

  useEffect(() => {
    void loadReminders();
    const timer = window.setInterval(() => void loadReminders(), 60_000);
    return () => window.clearInterval(timer);
  }, [loadReminders]);

  const dismissReminder = async (reminderId: string) => {
    setReminderError(undefined);
    try {
      await api.dismissReminder(reminderId);
      setReminders((current) => current.filter((item) => item.id !== reminderId));
    } catch (reason) {
      setReminderError(reason instanceof Error ? reason.message : "That suggestion could not be dismissed.");
    }
  };

  const filteredRoutines = useMemo(() => {
    const term = query.trim().toLocaleLowerCase();
    if (!term) return routines;
    return routines.filter((routine) => `${routine.name} ${routine.description ?? ""}`.toLocaleLowerCase().includes(term));
  }, [query, routines]);

  const findTask = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) return;
    setResolving(true);
    setError(undefined);
    try {
      setResolved(await api.resolveTasks(query.trim()));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "That task could not be searched.");
    } finally {
      setResolving(false);
    }
  };

  const checkEpisode = async (event: FormEvent) => {
    event.preventDefault();
    if (!episodeQuery.trim()) return;
    setEpisodeLoading(true);
    setEpisode(undefined);
    setEpisodeError(undefined);
    try {
      setEpisode(await api.answerEpisode(episodeQuery.trim()));
    } catch (reason) {
      setEpisodeError(reason instanceof Error ? reason.message : "Completed tasks could not be checked.");
    } finally {
      setEpisodeLoading(false);
    }
  };

  const visibleRoutines = resolved ?? filteredRoutines;

  const copyCaregiverCode = async () => {
    try {
      await navigator.clipboard.writeText(participant.userId);
      setCodeCopied(true);
      window.setTimeout(() => setCodeCopied(false), 1800);
    } catch {
      setCodeCopied(false);
    }
  };

  return (
    <main className="routine-page" id="main-content">
      <header className="page-heading page-heading--participant">
        <div>
          <span className="eyebrow">Welcome back</span>
          <h1>What can I help with today?</h1>
        </div>
        <div className="participant-heading-actions">
          <details className="caregiver-code">
            <summary><HeartHandshake aria-hidden="true" size={18} /> Caregiver code</summary>
            <div>
              <code>{participant.userId}</code>
              <button aria-label="Copy caregiver session code" className="icon-button icon-button--small" onClick={() => void copyCaregiverCode()} title="Copy caregiver session code" type="button">
                {codeCopied ? <Check aria-hidden="true" size={18} /> : <Copy aria-hidden="true" size={18} />}
              </button>
            </div>
            <span className="sr-only" role="status">{codeCopied ? "Caregiver session code copied" : ""}</span>
          </details>
          <button aria-label="Refresh saved routines" className="icon-button" onClick={() => void loadRoutines()} title="Refresh routines" type="button">
            <RefreshCw aria-hidden="true" size={23} />
          </button>
        </div>
      </header>

      <form className="task-search" onSubmit={findTask} role="search">
        <Search aria-hidden="true" size={24} />
        <label className="sr-only" htmlFor="task-query">Search routines or describe a task</label>
        <input
          autoComplete="off"
          id="task-query"
          onChange={(event) => {
            setQuery(event.target.value);
            setResolved(undefined);
          }}
          placeholder="Type a task, like pay the water bill"
          value={query}
        />
        <button className="button button--primary" disabled={!query.trim() || resolving} type="submit">
          {resolving ? "Searching" : "Find"}
          <ArrowRight aria-hidden="true" size={20} />
        </button>
      </form>

      {error ? <p className="form-error routine-error" role="alert">{error}</p> : null}
      {startError ? <p className="form-error routine-error" role="alert">{startError}</p> : null}
      {reminderError ? <p className="form-error routine-error" role="alert">{reminderError}</p> : null}

      {reminders.length > 0 ? (
        <section aria-labelledby="suggestion-title" aria-live="polite" className="proactive-reminders">
          <div className="section-heading-row">
            <div>
              <span className="section-kicker"><BellRing aria-hidden="true" size={19} /> From your usual routine</span>
              <h2 id="suggestion-title">Would you like to do this now?</h2>
            </div>
          </div>
          <div className="proactive-reminder-list">
            {reminders.map((reminder) => (
              <article className="proactive-reminder" key={reminder.id}>
                <BellRing aria-hidden="true" size={26} />
                <div>
                  <h3>{reminder.routine.name}</h3>
                  <p>{reminder.reason}</p>
                  <small>You’ve started this around the same time {reminder.occurrenceCount} times. Nothing opens until you choose Start.</small>
                </div>
                <div className="proactive-reminder__actions">
                  <button className="button button--primary" disabled={starting} onClick={() => void onStartReminder(reminder.id)} type="button">
                    {starting ? "Opening" : "Start this task"}
                    <ArrowRight aria-hidden="true" size={20} />
                  </button>
                  <button aria-label={`Dismiss ${reminder.routine.name} until tomorrow`} className="icon-button" onClick={() => void dismissReminder(reminder.id)} title="Not now" type="button">
                    <X aria-hidden="true" size={21} />
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <section className="routine-section" aria-labelledby="routine-list-title">
        <div className="section-heading-row">
          <div>
            <span className="section-kicker"><Sparkles aria-hidden="true" size={19} /> {resolved ? "Matches" : "Your tasks"}</span>
            <h2 id="routine-list-title">{resolved ? "Choose the task you meant" : "Choose a task to begin"}</h2>
          </div>
          {resolved ? <button className="text-button" onClick={() => setResolved(undefined)} type="button">Show all</button> : null}
        </div>

        {loading ? <div className="loading-line" role="status"><span className="spinner" /> Loading routines</div> : null}
        {!loading && visibleRoutines.length === 0 ? (
          <EmptyState
            action={error ? <button className="button button--secondary" onClick={() => void loadRoutines()} type="button"><RefreshCw aria-hidden="true" size={19} /> Try again</button> : undefined}
            icon={CircleHelp}
            message={resolved ? "No saved routine matched those words." : "No routines are available from memory yet."}
            title={resolved ? "No match found" : "No saved routines"}
          />
        ) : null}

        <div className="routine-grid">
          {visibleRoutines.map((routine) => (
            <article className="routine-card" key={routine.id}>
              <div className="routine-card__icon"><span aria-hidden="true">{routine.name.slice(0, 1).toLocaleUpperCase()}</span></div>
              <div className="routine-card__body">
                <h3>{routine.name}</h3>
                {routine.description ? <p>{routine.description}</p> : null}
                <div className="routine-card__meta">
                  {routine.replayReady ? <span><CheckCircle2 aria-hidden="true" size={17} /> Ready to guide you</span> : <span><Clock3 aria-hidden="true" size={17} /> I’ll guide you</span>}
                </div>
              </div>
              <div className="routine-card__actions">
                <button className="button button--primary" disabled={starting} onClick={() => void onStart(routine)} type="button">
                  {starting ? "Opening" : "Start this task"}
                  <ArrowRight aria-hidden="true" size={20} />
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="completion-lookup" aria-labelledby="completion-title">
        <div>
          <span className="section-kicker"><Clock3 aria-hidden="true" size={19} /> Completed tasks</span>
          <h2 id="completion-title">Check if something is done</h2>
        </div>
        <form onSubmit={checkEpisode}>
          <label className="sr-only" htmlFor="episode-query">Ask about a completed task</label>
          <input id="episode-query" onChange={(event) => setEpisodeQuery(event.target.value)} placeholder="Did I already pay the water bill?" value={episodeQuery} />
          <button className="button button--secondary" disabled={episodeLoading || !episodeQuery.trim()} type="submit">{episodeLoading ? "Checking" : "Check"}</button>
        </form>
        {episodeError ? <p className="form-error" role="alert">{episodeError}</p> : null}
        {episode ? (
          <div className={`episode-answer ${episode.found ? "episode-answer--found" : ""}`} role="status">
            {episode.found ? <CheckCircle2 aria-hidden="true" size={25} /> : <CircleHelp aria-hidden="true" size={25} />}
            <p>{episode.answer ?? (episode.found ? "A completion record was found." : "No matching completion was found.")}</p>
          </div>
        ) : null}
      </section>

    </main>
  );
}
