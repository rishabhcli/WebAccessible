import { useCallback, useEffect, useRef, useState } from "react";
import { HeartHandshake, House, LogOut, MousePointer2, UserRound } from "lucide-react";
import { api } from "./api/client";
import type { AgentRun, ParticipantContext, ReadinessSnapshot } from "./api/types";
import { AgentDashboard } from "./agent/AgentDashboard";
import { TaskLauncher } from "./agent/TaskLauncher";
import { CaregiverView } from "./caregiver/CaregiverView";
import { LandingPage } from "./landing/LandingPage";
import { ProviderStatus } from "./shared/ProviderStatus";
import { SlidesView } from "./slides/SlidesView";

const PARTICIPANT_STORAGE_KEY = "webaccessible.participant-session";
const CAREGIVER_STORAGE_KEY = "webaccessible.caregiver-session";
const PARTICIPANT_USER_ID_KEY = "webaccessible.participantUserId";

type AppView = "landing" | "participant" | "caregiver" | "slides";

function readContext(key: string): ParticipantContext | undefined {
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return undefined;
    const parsed = JSON.parse(raw) as ParticipantContext;
    if (!parsed.participantSessionId || !parsed.userId || !parsed.role) return undefined;
    return parsed;
  } catch {
    return undefined;
  }
}

function initialView(): AppView {
  if (window.location.pathname.startsWith("/slides")) return "slides";
  if (window.location.pathname.startsWith("/caregiver")) return "caregiver";
  if (window.location.pathname.startsWith("/participant")) return "participant";
  return "landing";
}

function participantUserId(): string {
  const existing = window.localStorage.getItem(PARTICIPANT_USER_ID_KEY);
  if (existing && /^wa-[0-9a-f-]{36}$/.test(existing)) return existing;
  const created = `wa-${crypto.randomUUID()}`;
  window.localStorage.setItem(PARTICIPANT_USER_ID_KEY, created);
  return created;
}

export default function App() {
  const [view, setView] = useState<AppView>(initialView);
  const [participant, setParticipant] = useState<ParticipantContext | undefined>(() => readContext(PARTICIPANT_STORAGE_KEY));
  const [caregiver, setCaregiver] = useState<ParticipantContext | undefined>(() => readContext(CAREGIVER_STORAGE_KEY));
  const [activeRun, setActiveRun] = useState<AgentRun>();
  const [participantLoading, setParticipantLoading] = useState(false);
  const [participantError, setParticipantError] = useState<string>();
  const [readiness, setReadiness] = useState<ReadinessSnapshot>();
  const [readinessLoading, setReadinessLoading] = useState(true);
  const [readinessError, setReadinessError] = useState<string>();
  const participantBootstrap = useRef<Promise<void> | null>(null);

  const activeContext = view === "caregiver" ? caregiver : participant;
  // Keep the shared API client in sync before child effects start loading protected data.
  // A passive effect here races dashboard requests after a hard refresh.
  api.setAccessToken(activeContext?.accessToken);

  const loadReadiness = useCallback(async () => {
    setReadinessLoading(true);
    setReadinessError(undefined);
    try {
      setReadiness(await api.readiness());
    } catch (reason) {
      setReadiness(undefined);
      setReadinessError(reason instanceof Error ? reason.message : "Service status could not be checked.");
    } finally {
      setReadinessLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadReadiness();
    const timer = window.setInterval(() => void loadReadiness(), 30_000);
    return () => window.clearInterval(timer);
  }, [loadReadiness]);

  useEffect(() => {
    const onPopState = () => setView(initialView());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = (nextView: AppView) => {
    setView(nextView);
    const path = nextView === "slides" ? "/slides" : nextView === "caregiver" ? "/caregiver" : nextView === "participant" ? "/participant" : "/";
    window.history.pushState({}, "", path);
    window.scrollTo({ top: 0, behavior: "auto" });
  };

  const openGuestParticipant = useCallback(async () => {
    if (participantBootstrap.current) return participantBootstrap.current;
    setParticipantLoading(true);
    setParticipantError(undefined);

    const request = (async () => {
      try {
        const context = await api.createParticipantSession({
          user_id: participantUserId(),
          role: "participant",
          preferences: {
            reading_size: "large",
            voice_enabled: true,
            activity_memory_enabled: false,
            proactive_reminders_enabled: false,
          },
        });
        setParticipant(context);
        window.sessionStorage.setItem(PARTICIPANT_STORAGE_KEY, JSON.stringify(context));
        api.setAccessToken(context.accessToken);
      } catch (reason) {
        setParticipantError(reason instanceof Error ? reason.message : "Your tasks could not be opened.");
      } finally {
        setParticipantLoading(false);
      }
    })();

    participantBootstrap.current = request;
    try {
      await request;
    } finally {
      if (participantBootstrap.current === request) participantBootstrap.current = null;
    }
  }, []);

  useEffect(() => {
    if (view === "participant" && !participant) void openGuestParticipant();
  }, [openGuestParticipant, participant, view]);

  const acceptCaregiver = (context: ParticipantContext) => {
    setCaregiver(context);
    window.sessionStorage.setItem(CAREGIVER_STORAGE_KEY, JSON.stringify(context));
    api.setAccessToken(context.accessToken);
    navigate("caregiver");
  };

  const signOutCaregiver = () => {
    window.sessionStorage.removeItem(CAREGIVER_STORAGE_KEY);
    setCaregiver(undefined);
    api.setAccessToken(undefined);
  };

  const readingClass = participant?.readingSize === "larger" && view === "participant" ? "reading-larger" : "reading-large";
  const showRoleNavigation = !activeRun;

  return (
    <div className={`app ${readingClass}`}>
      <a className="skip-link" href="#main-content">Skip to main content</a>
      {view === "slides" ? (
        <SlidesView />
      ) : view === "landing" ? (
        <LandingPage onCaregiver={() => navigate("caregiver")} onStart={() => navigate("participant")} />
      ) : (
        <>
          <header className={`app-header app-header--${view}`}>
            <button aria-label="WebAccessible home" className="brand" onClick={() => navigate("landing")} type="button">
              <span className="brand__mark"><MousePointer2 aria-hidden="true" size={23} /></span>
              <span className="brand__word">WebAccessible</span>
            </button>

            <div className="app-header__actions">
              {showRoleNavigation ? (
                <nav aria-label="View" className="role-switcher">
                  <button onClick={() => navigate("landing")} type="button"><House aria-hidden="true" size={18} /> Home</button>
                  <button aria-current={view === "participant" ? "page" : undefined} className={view === "participant" ? "active" : undefined} onClick={() => navigate("participant")} type="button"><UserRound aria-hidden="true" size={18} /> My tasks</button>
                  <button aria-current={view === "caregiver" ? "page" : undefined} className={view === "caregiver" ? "active" : undefined} onClick={() => navigate("caregiver")} type="button"><HeartHandshake aria-hidden="true" size={18} /> Caregiver</button>
                </nav>
              ) : null}
              {view === "caregiver" ? <ProviderStatus error={readinessError} loading={readinessLoading} onRefresh={() => void loadReadiness()} readiness={readiness} /> : null}
              {view === "caregiver" && caregiver && !activeRun ? (
                <button aria-label="End this signed-in session" className="icon-button" onClick={signOutCaregiver} title="Sign out" type="button"><LogOut aria-hidden="true" size={21} /></button>
              ) : null}
            </div>
          </header>

          {view === "caregiver" ? (
            <CaregiverView
              context={caregiver}
              onAuthenticated={acceptCaregiver}
              onParticipant={() => navigate("participant")}
              onRefreshProviders={() => void loadReadiness()}
              readiness={readiness}
              readinessError={readinessError}
              readinessLoading={readinessLoading}
            />
          ) : activeRun && participant ? (
            <AgentDashboard
              initialRun={activeRun}
              onExit={() => setActiveRun(undefined)}
              sessionId={activeRun.sessionId}
              taskName={activeRun.taskName}
            />
          ) : participant ? (
            <TaskLauncher onStarted={setActiveRun} />
          ) : (
            <main className="participant-entry" id="main-content">
              <div className="participant-entry__card" role={participantError ? "alert" : "status"}>
                {participantError ? (
                  <>
                    <h1>Your tasks could not be opened.</h1>
                    <p>{participantError}</p>
                    <div className="participant-entry__actions">
                      <button className="button button--primary button--large" disabled={participantLoading} onClick={() => void openGuestParticipant()} type="button">
                        {participantLoading ? "Opening" : "Try again"}
                      </button>
                      <button className="button button--quiet" onClick={() => navigate("caregiver")} type="button">Caregiver console</button>
                    </div>
                  </>
                ) : (
                  <>
                    <span className="large-spinner" aria-hidden="true" />
                    <h1>Opening your tasks…</h1>
                    <p>No sign-up needed.</p>
                  </>
                )}
              </div>
            </main>
          )}
        </>
      )}
    </div>
  );
}
