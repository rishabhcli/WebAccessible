import { useCallback, useEffect, useState } from "react";
import { HeartHandshake, House, LogOut, MousePointer2, UserRound } from "lucide-react";
import { api } from "./api/client";
import type { ParticipantContext, ReadinessSnapshot, Routine, SessionSnapshot } from "./api/types";
import { CaregiverView } from "./caregiver/CaregiverView";
import { LandingPage } from "./landing/LandingPage";
import { RoutineChooser } from "./routines/RoutineChooser";
import { ParticipantSession } from "./session/ParticipantSession";
import { ProviderStatus } from "./shared/ProviderStatus";
import { SetupView } from "./setup/SetupView";

const PARTICIPANT_STORAGE_KEY = "webaccessible.participant-session";
const CAREGIVER_STORAGE_KEY = "webaccessible.caregiver-session";

type AppView = "landing" | "participant" | "caregiver";

interface ActiveSession {
  snapshot: SessionSnapshot;
  liveViewUrl?: string;
}

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
  if (window.location.pathname.startsWith("/caregiver")) return "caregiver";
  if (window.location.pathname.startsWith("/participant")) return "participant";
  return "landing";
}

export default function App() {
  const [view, setView] = useState<AppView>(initialView);
  const [participant, setParticipant] = useState<ParticipantContext | undefined>(() => readContext(PARTICIPANT_STORAGE_KEY));
  const [caregiver, setCaregiver] = useState<ParticipantContext | undefined>(() => readContext(CAREGIVER_STORAGE_KEY));
  const [activeSession, setActiveSession] = useState<ActiveSession>();
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string>();
  const [readiness, setReadiness] = useState<ReadinessSnapshot>();
  const [readinessLoading, setReadinessLoading] = useState(true);
  const [readinessError, setReadinessError] = useState<string>();

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
    const path = nextView === "caregiver" ? "/caregiver" : nextView === "participant" ? "/participant" : "/";
    window.history.pushState({}, "", path);
    window.scrollTo({ top: 0, behavior: "auto" });
  };

  const acceptParticipant = (context: ParticipantContext) => {
    setParticipant(context);
    window.sessionStorage.setItem(PARTICIPANT_STORAGE_KEY, JSON.stringify(context));
    api.setAccessToken(context.accessToken);
    navigate("participant");
  };

  const acceptCaregiver = (context: ParticipantContext) => {
    setCaregiver(context);
    window.sessionStorage.setItem(CAREGIVER_STORAGE_KEY, JSON.stringify(context));
    api.setAccessToken(context.accessToken);
    navigate("caregiver");
  };

  const signOut = () => {
    const key = view === "caregiver" ? CAREGIVER_STORAGE_KEY : PARTICIPANT_STORAGE_KEY;
    window.sessionStorage.removeItem(key);
    if (view === "caregiver") setCaregiver(undefined);
    else setParticipant(undefined);
    api.setAccessToken(undefined);
  };

  const startRoutine = async (routine: Routine) => {
    if (!participant) return;
    setStarting(true);
    setStartError(undefined);
    let created: SessionSnapshot | undefined;
    try {
      api.setAccessToken(participant.accessToken);
      created = await api.startTask(routine.id, participant.participantSessionId, routine.replayReady ? "replay" : "cold_teach");
      await attachCreatedSession(created, routine);
    } catch (reason) {
      if (created) {
        try {
          await api.stopBrowser(created.id, "start_failed");
        } catch {
          // Provider cleanup failure is reconciled by the backend lifecycle service.
        }
      }
      setStartError(reason instanceof Error ? reason.message : "The task could not be started.");
    } finally {
      setStarting(false);
    }
  };

  const attachCreatedSession = async (created: SessionSnapshot, routine?: Routine) => {
    if (!participant) throw new Error("The participant session is unavailable.");
    const attached = await api.attachBrowser(created.id);
    const snapshot: SessionSnapshot = {
      ...created,
      ...attached,
      id: created.id,
      userId: attached.userId ?? created.userId ?? participant.userId,
      participantSessionId: attached.participantSessionId ?? created.participantSessionId ?? participant.participantSessionId,
      browserbaseSessionId: attached.browserbaseSessionId ?? created.browserbaseSessionId,
      task: {
        id: attached.task?.id ?? created.task?.id ?? routine?.id,
        name: attached.task?.name ?? created.task?.name ?? routine?.name ?? "Suggested task",
        mode: attached.task?.mode ?? created.task?.mode ?? (routine?.replayReady ? "replay" : "cold"),
        skillId: attached.task?.skillId ?? created.task?.skillId ?? routine?.skillId,
        skillRevision: attached.task?.skillRevision ?? created.task?.skillRevision ?? routine?.revision,
      },
    };
    setActiveSession({ snapshot });
  };

  const startReminder = async (reminderId: string) => {
    if (!participant) return;
    setStarting(true);
    setStartError(undefined);
    let created: SessionSnapshot | undefined;
    try {
      api.setAccessToken(participant.accessToken);
      created = await api.acceptReminder(reminderId);
      await attachCreatedSession(created);
    } catch (reason) {
      if (created) {
        try {
          await api.stopBrowser(created.id, "start_failed");
        } catch {
          // Provider cleanup failure is reconciled by the backend lifecycle service.
        }
      }
      setStartError(reason instanceof Error ? reason.message : "The suggested task could not be started.");
    } finally {
      setStarting(false);
    }
  };

  const readingClass = participant?.readingSize === "larger" && view === "participant" ? "reading-larger" : "reading-large";
  const showRoleNavigation = !activeSession;

  return (
    <div className={`app ${readingClass}`}>
      <a className="skip-link" href="#main-content">Skip to main content</a>
      {view === "landing" ? (
        <LandingPage hasParticipant={Boolean(participant)} onCaregiver={() => navigate("caregiver")} onStart={() => navigate("participant")} />
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
              {activeContext && !activeSession ? (
                <button aria-label="End this signed-in session" className="icon-button" onClick={signOut} title="Sign out" type="button"><LogOut aria-hidden="true" size={21} /></button>
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
          ) : activeSession && participant ? (
            <ParticipantSession initial={activeSession.snapshot} initialLiveViewUrl={activeSession.liveViewUrl} onExit={() => setActiveSession(undefined)} participant={participant} />
          ) : participant ? (
            <RoutineChooser onStart={startRoutine} onStartReminder={startReminder} participant={participant} startError={startError} starting={starting} />
          ) : (
            <SetupView onCaregiver={() => navigate("caregiver")} onComplete={acceptParticipant} />
          )}
        </>
      )}
    </div>
  );
}
