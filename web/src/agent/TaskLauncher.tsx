import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowRight, BellRing, CalendarClock, Landmark, Sparkles, ShoppingCart, X } from "lucide-react";
import { api } from "../api/client";
import type { AgentRun, DemoTask, EpisodeAnswer, ProactiveReminder } from "../api/types";

interface TaskLauncherProps {
  onStarted: (run: AgentRun) => void;
}

const CATEGORY_ICON = {
  government: Landmark,
  shopping: ShoppingCart,
  appointment: CalendarClock,
} as const;

/**
 * Where a task begins: three ready errands, or anything typed in your own words.
 *
 * The ready tasks exist because they are the errands that recur. The prompt box is not a
 * lesser path — it takes any goal and starts from a site you name or the agent finds.
 */
export function TaskLauncher({ onStarted }: TaskLauncherProps) {
  const [demos, setDemos] = useState<DemoTask[]>([]);
  const [prompt, setPrompt] = useState("");
  const [startUrl, setStartUrl] = useState("");
  const [startingId, setStartingId] = useState<string>();
  const [error, setError] = useState<string>();
  const [reminders, setReminders] = useState<ProactiveReminder[]>([]);
  const [recallQuery, setRecallQuery] = useState("");
  const [recall, setRecall] = useState<EpisodeAnswer>();
  const [recalling, setRecalling] = useState(false);

  useEffect(() => {
    void api.listDemos().then(setDemos).catch(() => setDemos([]));
  }, []);

  const loadReminders = useCallback(async () => {
    try {
      setReminders(await api.listReminders());
    } catch {
      setReminders([]);
    }
  }, []);

  useEffect(() => {
    void loadReminders();
  }, [loadReminders]);

  // Reminders are pushed, so one that comes due while this screen is open arrives on its own.
  useEffect(() => {
    const controller = new AbortController();
    let reconnect: number | undefined;
    const subscribe = () => {
      void api
        .streamParticipant(controller.signal, (reminder) => {
          setReminders((current) => (current.some((item) => item.id === reminder.id) ? current : [...current, reminder]));
        })
        .catch(() => undefined)
        .finally(() => {
          if (controller.signal.aborted) return;
          reconnect = window.setTimeout(subscribe, 5_000);
        });
    };
    subscribe();
    return () => {
      controller.abort();
      if (reconnect !== undefined) window.clearTimeout(reconnect);
    };
  }, []);

  const start = async (id: string, body: { prompt: string; demo_id?: string; start_url?: string }) => {
    setStartingId(id);
    setError(undefined);
    try {
      onStarted(await api.startAgentRun(body));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "That task could not be started.");
    } finally {
      setStartingId(undefined);
    }
  };

  const submitPrompt = (event: FormEvent) => {
    event.preventDefault();
    if (!prompt.trim()) return;
    void start("prompt", {
      prompt: prompt.trim(),
      start_url: startUrl.trim() || undefined,
    });
  };

  const askRecall = async (event: FormEvent) => {
    event.preventDefault();
    if (!recallQuery.trim()) return;
    setRecalling(true);
    setRecall(undefined);
    try {
      setRecall(await api.answerEpisode(recallQuery.trim()));
    } catch {
      setRecall({ found: false, answer: "I could not check that just now." });
    } finally {
      setRecalling(false);
    }
  };

  const dismissReminder = async (reminderId: string) => {
    setReminders((current) => current.filter((item) => item.id !== reminderId));
    await api.dismissReminder(reminderId).catch(() => undefined);
  };

  return (
    <main className="launcher page-enter" id="main-content">
      <header className="launcher__header">
        <h1>What would you like done?</h1>
        <p>Pick one, or just say it. I&apos;ll open a browser and do it while you watch.</p>
      </header>

      {reminders.length > 0 ? (
        <section aria-label="Suggestions" className="launcher__reminders">
          {reminders.map((reminder) => (
            <div className="reminder fade-in-up" key={reminder.id}>
              <span className="reminder__icon"><BellRing aria-hidden="true" size={19} /></span>
              <p>{reminder.reason}</p>
              <div className="reminder__actions">
                <button
                  className="button button--primary button--small"
                  disabled={Boolean(startingId)}
                  onClick={() => void start(reminder.id, { prompt: reminder.routine.name })}
                  type="button"
                >
                  Yes, do it
                </button>
                <button aria-label="Dismiss this suggestion" className="icon-button icon-button--small" onClick={() => void dismissReminder(reminder.id)} type="button">
                  <X aria-hidden="true" size={17} />
                </button>
              </div>
            </div>
          ))}
        </section>
      ) : null}

      <section aria-label="Ready tasks" className="demo-grid">
        {demos.map((demo, index) => {
          const Icon = CATEGORY_ICON[demo.category];
          return (
            <button
              className="demo-card fade-in-up"
              disabled={Boolean(startingId)}
              key={demo.id}
              onClick={() => void start(demo.id, { prompt: demo.prompt, demo_id: demo.id })}
              style={{ animationDelay: `${index * 70}ms` }}
              type="button"
            >
              <span className={`demo-card__icon demo-card__icon--${demo.category}`}>
                <Icon aria-hidden="true" size={26} />
              </span>
              <h2>{demo.name}</h2>
              <p>{demo.description}</p>
              <span className="demo-card__go">
                {startingId === demo.id ? <><span className="spinner spinner--small" /> Opening</> : <>Start <ArrowRight aria-hidden="true" size={18} /></>}
              </span>
            </button>
          );
        })}
        {demos.length === 0 ? Array.from({ length: 3 }, (_, index) => <div className="demo-card demo-card--skeleton" key={index} />) : null}
      </section>

      <form className="prompt-box" onSubmit={submitPrompt}>
        <label htmlFor="agent-prompt">
          <Sparkles aria-hidden="true" size={19} /> Or ask for anything
        </label>
        <textarea
          id="agent-prompt"
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Renew my library book, or order more cat food"
          rows={2}
          value={prompt}
        />
        <div className="prompt-box__row">
          <input
            aria-label="Website to start from, if you know it"
            onChange={(event) => setStartUrl(event.target.value)}
            placeholder="Start at a website (optional)"
            type="url"
            value={startUrl}
          />
          <button className="button button--primary" disabled={!prompt.trim() || Boolean(startingId)} type="submit">
            {startingId === "prompt" ? <><span className="spinner spinner--small" /> Starting</> : <>Do it <ArrowRight aria-hidden="true" size={18} /></>}
          </button>
        </div>
      </form>

      {error ? <p className="form-error" role="alert">{error}</p> : null}

      <form className="recall-box" onSubmit={askRecall}>
        <label htmlFor="recall-query">Already done? Ask me.</label>
        <div className="recall-box__row">
          <input
            id="recall-query"
            onChange={(event) => setRecallQuery(event.target.value)}
            placeholder="When's the DMV appointment you booked?"
            value={recallQuery}
          />
          <button className="button button--secondary" disabled={!recallQuery.trim() || recalling} type="submit">
            {recalling ? <span className="spinner spinner--small" /> : "Ask"}
          </button>
        </div>
        {recall ? <p className="recall-box__answer fade-in-up" role="status">{recall.answer}</p> : null}
      </form>
    </main>
  );
}
