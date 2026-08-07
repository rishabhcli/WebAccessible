import { useState, type FormEvent } from "react";
import { ArrowRight, BellRing, Brain, Check, Eye, EyeOff, ShieldCheck, Smartphone, Type, Volume2 } from "lucide-react";
import { api } from "../api/client";
import type { ParticipantContext, ReadingSize } from "../api/types";

interface SetupViewProps {
  onComplete: (context: ParticipantContext) => void;
  onCaregiver: () => void;
}

const PARTICIPANT_USER_ID_KEY = "webaccessible.participantUserId";

function participantUserId(): string {
  const existing = window.localStorage.getItem(PARTICIPANT_USER_ID_KEY);
  if (existing && /^wa-[0-9a-f-]{36}$/.test(existing)) return existing;
  const created = `wa-${crypto.randomUUID()}`;
  window.localStorage.setItem(PARTICIPANT_USER_ID_KEY, created);
  return created;
}

export function SetupView({ onComplete, onCaregiver }: SetupViewProps) {
  const [userId] = useState(participantUserId);
  const [name, setName] = useState("");
  const [caregiverMobile, setCaregiverMobile] = useState("");
  const [readingSize, setReadingSize] = useState<ReadingSize>("large");
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [activityMemoryEnabled, setActivityMemoryEnabled] = useState(false);
  const [proactiveRemindersEnabled, setProactiveRemindersEnabled] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(undefined);
    try {
      const context = await api.createParticipantSession({
        user_id: userId,
        role: "participant",
        participant_name: name.trim(),
        caregiver_mobile: caregiverMobile.trim() || undefined,
        preferences: {
          reading_size: readingSize,
          voice_enabled: voiceEnabled,
          activity_memory_enabled: activityMemoryEnabled,
          proactive_reminders_enabled: proactiveRemindersEnabled,
        },
      });
      onComplete(context);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Setup could not be completed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="setup-shell" id="main-content">
      <section className="setup-intro" aria-labelledby="setup-title">
        <span className="section-kicker"><ShieldCheck aria-hidden="true" size={20} /> Your private setup</span>
        <h1 id="setup-title">Let’s make this comfortable.</h1>
        <p>Choose what helps. You can change these settings later.</p>
        <div className="setup-trust-list" aria-label="WebAccessible boundaries">
          <span><Check aria-hidden="true" size={20} /> You make every click.</span>
          <span><Check aria-hidden="true" size={20} /> Passwords stay in the browser.</span>
          <span><Check aria-hidden="true" size={20} /> Money steps always pause.</span>
        </div>
      </section>

      <form className="setup-form" onSubmit={submit}>
        <div className="form-heading">
          <h2>Tell us what helps</h2>
          <p>Only your first name is required.</p>
        </div>

        <label className="field">
          <span>Your first name <span aria-hidden="true">*</span></span>
          <input
            autoComplete="given-name"
            autoFocus
            name="participantName"
            onChange={(event) => setName(event.target.value)}
            placeholder="First name"
            required
            value={name}
          />
        </label>

        <label className="field">
          <span><Smartphone aria-hidden="true" size={19} /> Caregiver phone <small>(optional)</small></span>
          <input
            autoComplete="tel"
            inputMode="tel"
            name="caregiverMobile"
            onChange={(event) => setCaregiverMobile(event.target.value)}
            placeholder="Mobile number"
            type="tel"
            value={caregiverMobile}
          />
        </label>

        <fieldset className="fieldset-reset">
          <legend><Type aria-hidden="true" size={19} /> Reading size</legend>
          <div className="segmented-control segmented-control--wide">
            <label className={readingSize === "large" ? "selected" : undefined}>
              <input checked={readingSize === "large"} name="readingSize" onChange={() => setReadingSize("large")} type="radio" />
              <span>Large</span>
            </label>
            <label className={readingSize === "larger" ? "selected" : undefined}>
              <input checked={readingSize === "larger"} name="readingSize" onChange={() => setReadingSize("larger")} type="radio" />
              <span className="larger-sample">Extra large</span>
            </label>
          </div>
        </fieldset>

        <label className="toggle-row">
          <span className="toggle-row__icon"><Volume2 aria-hidden="true" size={21} /></span>
          <span className="toggle-row__copy">
            <strong>Read each step aloud</strong>
            <small>Voice can be changed during a task.</small>
          </span>
          <input checked={voiceEnabled} onChange={(event) => setVoiceEnabled(event.target.checked)} type="checkbox" />
          <span aria-hidden="true" className="switch"><span /></span>
        </label>

        <label className="toggle-row">
          <span className="toggle-row__icon"><Brain aria-hidden="true" size={21} /></span>
          <span className="toggle-row__copy">
            <strong>Remember my routines</strong>
            <small>Remember when and how you usually start a task. Passwords and anything you type are never saved.</small>
          </span>
          <input
            checked={activityMemoryEnabled}
            onChange={(event) => {
              setActivityMemoryEnabled(event.target.checked);
              if (!event.target.checked) setProactiveRemindersEnabled(false);
            }}
            type="checkbox"
          />
          <span aria-hidden="true" className="switch"><span /></span>
        </label>

        <label className="toggle-row">
          <span className="toggle-row__icon"><BellRing aria-hidden="true" size={21} /></span>
          <span className="toggle-row__copy">
            <strong>Remind me when it’s usually time</strong>
            <small>A gentle note appears here. You choose whether to start.</small>
          </span>
          <input
            checked={proactiveRemindersEnabled}
            disabled={!activityMemoryEnabled}
            onChange={(event) => setProactiveRemindersEnabled(event.target.checked)}
            type="checkbox"
          />
          <span aria-hidden="true" className="switch"><span /></span>
        </label>

        {error ? <p className="form-error" role="alert">{error}</p> : null}

        <button className="button button--primary button--large" disabled={submitting || !name.trim()} type="submit">
          {submitting ? "Saving" : "Save and show my tasks"}
          <ArrowRight aria-hidden="true" size={22} />
        </button>

        <button className="text-button setup-caregiver-link" onClick={onCaregiver} type="button">
          {voiceEnabled ? <Eye aria-hidden="true" size={19} /> : <EyeOff aria-hidden="true" size={19} />}
          Caregiver access
        </button>
      </form>
    </main>
  );
}
