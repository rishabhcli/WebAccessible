import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  CheckCircle2,
  HeartHandshake,
  LockKeyhole,
  MousePointer2,
  Play,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Volume2,
} from "lucide-react";

interface LandingPageProps {
  hasParticipant: boolean;
  onCaregiver: () => void;
  onStart: () => void;
}

type DemoPhase = "start" | "find" | "guided" | "review" | "paused" | "done";

const guidanceByPhase: Record<DemoPhase, string> = {
  start: "Ready when you are.",
  find: "I'll give you a moment to look around.",
  guided: "Choose Billing & payments to continue.",
  review: "Choose Review payment to check the final amount.",
  paused: "Check the total, then choose Pay $42.80 when you are ready.",
  done: "You did it - the water bill demo is complete.",
};

function PixelMascot({ phase }: { phase: DemoPhase }) {
  return (
    <div className={`pixel-pal pixel-pal--${phase}`} role="img" aria-label="Dot, the WebAccessible pixel guide">
      <span className="pixel-pal__signal" />
      <span className="pixel-pal__antenna"><span /></span>
      <span className="pixel-pal__ear pixel-pal__ear--left" />
      <span className="pixel-pal__ear pixel-pal__ear--right" />
      <span className="pixel-pal__head">
        <span className="pixel-pal__screen">
          <span className="pixel-pal__eye pixel-pal__eye--left" />
          <span className="pixel-pal__eye pixel-pal__eye--right" />
          <span className="pixel-pal__mouth" />
        </span>
      </span>
      <span className="pixel-pal__body"><MousePointer2 aria-hidden="true" size={25} /></span>
      <span className="pixel-pal__arm pixel-pal__arm--left" />
      <span className="pixel-pal__arm pixel-pal__arm--right" />
      <span className="pixel-pal__foot pixel-pal__foot--left" />
      <span className="pixel-pal__foot pixel-pal__foot--right" />
      <span className="pixel-pal__ground" />
    </div>
  );
}

export function LandingPage({ hasParticipant, onCaregiver, onStart }: LandingPageProps) {
  const [phase, setPhase] = useState<DemoPhase>("start");
  const [wrongChoice, setWrongChoice] = useState<string>();
  const demoRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (phase !== "find") return;
    const timer = window.setTimeout(() => setPhase("guided"), 4_500);
    return () => window.clearTimeout(timer);
  }, [phase]);

  const beginDemo = () => {
    setWrongChoice(undefined);
    setPhase("find");
    window.setTimeout(() => demoRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
  };

  const chooseWrong = (choice: string) => {
    setWrongChoice(choice);
    setPhase("guided");
  };

  const resetDemo = () => {
    setWrongChoice(undefined);
    setPhase("start");
  };

  const progress = phase === "start" || phase === "find" || phase === "guided" ? 1 : phase === "review" || phase === "paused" ? 2 : 3;

  return (
    <main className="landing-page" id="main-content">
      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero__echo" aria-hidden="true">YOU CLICK</div>
        <nav className="landing-nav" aria-label="Primary navigation">
          <a className="landing-brand" href="/" aria-label="WebAccessible home">
            <span className="landing-brand__mark"><MousePointer2 aria-hidden="true" size={21} /></span>
            <span>WebAccessible</span>
          </a>
          <div className="landing-nav__actions">
            <button className="landing-nav__caregiver" onClick={onCaregiver} type="button">
              <HeartHandshake aria-hidden="true" size={19} />
              <span>Caregiver access</span>
            </button>
            <button className="landing-button landing-button--ink landing-button--compact" onClick={onStart} type="button">
              {hasParticipant ? "Open my routines" : "Set up my browser"}
              <ArrowRight aria-hidden="true" size={18} />
            </button>
          </div>
        </nav>

        <div className="landing-hero__copy">
          <div className="landing-kicker"><span /> Browser guidance that waits for you</div>
          <h1 id="landing-title">WebAccessible</h1>
          <p>A steady hand through confusing websites, one clear step at a time.</p>
          <div className="landing-hero__actions">
            <button className="landing-button landing-button--coral" onClick={beginDemo} type="button">
              <Play aria-hidden="true" fill="currentColor" size={19} /> Try it right here
            </button>
            <span className="landing-hero__note"><LockKeyhole aria-hidden="true" size={18} /> No account or real payment</span>
          </div>
        </div>

        <div className="demo-stage" id="demo-playground" ref={demoRef}>
          <div className="demo-stage__header">
            <div>
              <span className="demo-stage__label"><span /> LIVE PLAYGROUND</span>
              <strong>Pay the water bill</strong>
            </div>
            <div className="demo-progress" aria-label={`Demo step ${progress} of 3`}>
              {[1, 2, 3].map((step) => <span className={step <= progress ? "active" : undefined} key={step}>{step}</span>)}
            </div>
          </div>

          <div className="demo-stage__experience">
            <div className="demo-browser">
              <div className="demo-browser__bar">
                <span className="demo-browser__lights" aria-hidden="true"><i /><i /><i /></span>
                <span className="demo-browser__address"><LockKeyhole aria-hidden="true" size={14} /> citywater.example</span>
                <span className="demo-browser__badge">DEMO ONLY</span>
              </div>

              <div className="demo-browser__page" aria-live="polite">
                {phase === "start" ? (
                  <div className="demo-start">
                    <span className="demo-start__icon"><MousePointer2 aria-hidden="true" size={32} /></span>
                    <p className="demo-overline">A 30-second practice run</p>
                    <h2>You make every click.</h2>
                    <p>Dot steps in only when the next move gets confusing.</p>
                    <button className="demo-site-button demo-site-button--primary" onClick={beginDemo} type="button">
                      Start the demo <ArrowRight aria-hidden="true" size={20} />
                    </button>
                  </div>
                ) : null}

                {phase === "find" || phase === "guided" ? (
                  <div className="demo-utility">
                    <div className="demo-utility__masthead">
                      <span className="demo-water-drop" aria-hidden="true" />
                      <span><strong>City Water</strong><small>Customer portal</small></span>
                    </div>
                    <div className="demo-task-ribbon"><span>Your task</span><strong>Pay the water bill</strong></div>
                    <div className="demo-choice-grid">
                      <button onClick={() => chooseWrong("Water usage")} type="button"><span>01</span><strong>Water usage</strong><small>See this month's gallons</small></button>
                      <button onClick={() => chooseWrong("Start or stop service")} type="button"><span>02</span><strong>Start or stop service</strong><small>Move or change an address</small></button>
                      <button className={phase === "guided" ? "demo-target" : undefined} onClick={() => { setWrongChoice(undefined); setPhase("review"); }} type="button"><span>03</span><strong>Billing &amp; payments</strong><small>View and pay your balance</small></button>
                    </div>
                    {wrongChoice ? <p className="demo-soft-note">"{wrongChoice}" wasn't it, and that's alright.</p> : null}
                  </div>
                ) : null}

                {phase === "review" ? (
                  <div className="demo-bill">
                    <div className="demo-bill__topline"><span>Current balance</span><span>Due August 20</span></div>
                    <div className="demo-bill__amount"><sup>$</sup>42<small>.80</small></div>
                    <dl>
                      <div><dt>Account</dt><dd>City Water ending 4471</dd></div>
                      <div><dt>Payment method</dt><dd>Checking ending 2086</dd></div>
                    </dl>
                    <button className="demo-site-button demo-site-button--primary demo-target" onClick={() => setPhase("paused")} type="button">
                      Review payment <ArrowRight aria-hidden="true" size={20} />
                    </button>
                  </div>
                ) : null}

                {phase === "paused" ? (
                  <div className="demo-confirm">
                    <span className="demo-confirm__shield"><ShieldCheck aria-hidden="true" size={35} /></span>
                    <p className="demo-overline">Pause before payment</p>
                    <h2>Pay $42.80 to City Water?</h2>
                    <p>Nothing happens until you choose the real button.</p>
                    <div className="demo-confirm__total"><span>Total</span><strong>$42.80</strong></div>
                    <div className="demo-confirm__actions">
                      <button className="demo-site-button" onClick={() => setPhase("review")} type="button">Go back</button>
                      <button className="demo-site-button demo-site-button--primary demo-target" onClick={() => setPhase("done")} type="button">Pay $42.80</button>
                    </div>
                    <small>This is a simulation; no payment will be sent.</small>
                  </div>
                ) : null}

                {phase === "done" ? (
                  <div className="demo-done">
                    <span className="demo-pixel-burst" aria-hidden="true"><i /><i /><i /><i /><i /><i /></span>
                    <CheckCircle2 aria-hidden="true" size={54} strokeWidth={2.5} />
                    <p className="demo-overline">Routine complete</p>
                    <h2>You paid the demo bill.</h2>
                    <p>You stayed in control from start to finish.</p>
                    <button className="demo-site-button" onClick={resetDemo} type="button"><RotateCcw aria-hidden="true" size={19} /> Run it again</button>
                  </div>
                ) : null}
              </div>
            </div>

            <aside className="demo-companion" aria-label="WebAccessible guidance">
              <div className="demo-companion__status"><span className={phase === "guided" || phase === "paused" ? "active" : undefined} /> DOT // {phase === "guided" ? "HELPING" : phase === "paused" ? "CHECKING" : phase === "done" ? "CELEBRATING" : "STANDING BY"}</div>
              <div className="demo-companion__speech" aria-live="polite">{guidanceByPhase[phase]}</div>
              <PixelMascot phase={phase} />
              <div className="demo-companion__boundary"><MousePointer2 aria-hidden="true" size={18} /> Your pointer. Your decision.</div>
            </aside>
          </div>
        </div>

        <div className="landing-hero__foot">
          <span>Keep scrolling</span>
          <span>ONE STEP / ONE CLICK / STILL YOURS</span>
        </div>
      </section>

      <section className="landing-manifesto" aria-labelledby="manifesto-title">
        <div className="landing-manifesto__label">THE DIFFERENCE</div>
        <div className="landing-manifesto__copy">
          <h2 id="manifesto-title">It doesn't browse for you.<br /><em>It keeps you browsing.</em></h2>
          <p>WebAccessible notices a stuck moment, points to one next step, and waits. Every click, keystroke, and final decision stays with the person at the keyboard.</p>
        </div>
        <MousePointer2 className="landing-manifesto__cursor" aria-hidden="true" size={118} strokeWidth={1.2} />
      </section>

      <section className="landing-rules" aria-labelledby="rules-title">
        <div className="landing-section-heading">
          <p>Built around dignity</p>
          <h2 id="rules-title">Three rules we won't break.</h2>
        </div>
        <div className="landing-rule-list">
          <article>
            <span>01</span>
            <div><h3>You do the doing.</h3><p>WebAccessible can highlight and explain, but it never clicks or submits for you.</p></div>
            <MousePointer2 aria-hidden="true" size={34} />
          </article>
          <article>
            <span>02</span>
            <div><h3>One clear step.</h3><p>No giant checklists and no scolding. Just the next move, in plain language.</p></div>
            <Sparkles aria-hidden="true" size={34} />
          </article>
          <article>
            <span>03</span>
            <div><h3>Money always pauses.</h3><p>Before payment, personal data, or deletion, the final choice is made unmistakably clear.</p></div>
            <ShieldCheck aria-hidden="true" size={34} />
          </article>
        </div>
      </section>

      <section className="landing-people" aria-labelledby="people-title">
        <div className="landing-people__participant">
          <p className="landing-people__eyebrow">FOR THE PERSON BROWSING</p>
          <h2 id="people-title">"I did it myself."</h2>
          <p>Familiar routines stay familiar. Reading can be larger, steps can be read aloud, and help arrives without taking over.</p>
          <div className="landing-people__proof"><Volume2 aria-hidden="true" size={22} /><span><strong>One sentence at a time</strong><small>Shown and spoken when useful</small></span></div>
        </div>
        <div className="landing-people__caregiver">
          <p className="landing-people__eyebrow">FOR SOMEONE WHO CARES</p>
          <h2>Close by, without hovering.</h2>
          <p>Caregivers can teach a routine once, see when help is truly needed, and send a calm note from anywhere.</p>
          <button className="landing-button landing-button--cream" onClick={onCaregiver} type="button">Caregiver access <ArrowRight aria-hidden="true" size={19} /></button>
        </div>
      </section>

      <section className="landing-final" aria-labelledby="final-title">
        <PixelMascot phase="done" />
        <div>
          <p>YOUR WEB. YOUR PACE.</p>
          <h2 id="final-title">Ready for a steadier browser?</h2>
        </div>
        <button className="landing-button landing-button--coral" onClick={onStart} type="button">
          {hasParticipant ? "Open my routines" : "Set up WebAccessible"}
          <ArrowRight aria-hidden="true" size={20} />
        </button>
      </section>

      <footer className="landing-footer">
        <a className="landing-brand landing-brand--footer" href="/"><span className="landing-brand__mark"><MousePointer2 aria-hidden="true" size={20} /></span><span>WebAccessible</span></a>
        <p><Check aria-hidden="true" size={17} /> Passwords are never requested or stored.</p>
        <button onClick={onCaregiver} type="button">Caregiver access</button>
      </footer>
    </main>
  );
}
