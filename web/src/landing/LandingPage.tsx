import {
  ArrowRight,
  Check,
  HeartHandshake,
  LockKeyhole,
  MousePointer2,
  ShieldCheck,
  Sparkles,
  UserRound,
  Volume2,
} from "lucide-react";

interface LandingPageProps {
  onCaregiver: () => void;
  onStart: () => void;
}

export function LandingPage({ onCaregiver, onStart }: LandingPageProps) {
  return (
    <main className="welcome-page" id="main-content">
      <nav className="welcome-nav" aria-label="Primary navigation">
        <a className="welcome-brand" href="/" aria-label="WebAccessible home">
          <span><MousePointer2 aria-hidden="true" size={24} /></span>
          WebAccessible
        </a>
        <button className="welcome-nav__caregiver" onClick={onCaregiver} type="button">
          <HeartHandshake aria-hidden="true" size={21} /> Caregiver console
        </button>
      </nav>

      <section className="welcome-hero" aria-labelledby="welcome-title">
        <div className="welcome-hero__copy">
          <span className="welcome-kicker"><Sparkles aria-hidden="true" size={19} /> Calm help for confusing websites</span>
          <h1 id="welcome-title">The web, one clear step at a time.</h1>
          <p>WebAccessible shows you what to do next, then waits while you make the click.</p>
          <div className="welcome-actions">
            <button className="welcome-button welcome-button--primary" onClick={onStart} type="button">
              <UserRound aria-hidden="true" size={23} />
              Open my tasks
              <ArrowRight aria-hidden="true" size={22} />
            </button>
            <button className="welcome-button welcome-button--secondary" onClick={onCaregiver} type="button">
              <HeartHandshake aria-hidden="true" size={22} /> Caregiver console
            </button>
          </div>
          <div className="welcome-trust" aria-label="WebAccessible promises">
            <span><Check aria-hidden="true" size={19} /> You stay in control</span>
            <span><LockKeyhole aria-hidden="true" size={19} /> Passwords stay private</span>
            <span><ShieldCheck aria-hidden="true" size={19} /> Money steps always pause</span>
          </div>
        </div>

        <div className="welcome-preview" aria-label="Example WebAccessible guidance">
          <div className="welcome-preview__top">
            <span className="welcome-preview__dots" aria-hidden="true"><i /><i /><i /></span>
            <span>City Water</span>
            <span className="welcome-preview__safe"><LockKeyhole aria-hidden="true" size={14} /> Practice</span>
          </div>
          <div className="welcome-preview__body">
            <div className="welcome-preview__site">
              <p>Pay the water bill</p>
              <span>Water use</span>
              <span className="welcome-preview__target">Billing &amp; payments</span>
              <span>Account details</span>
            </div>
            <aside className="welcome-preview__guide">
              <span>Next step</span>
              <MousePointer2 aria-hidden="true" size={36} />
              <strong>Choose “Billing &amp; payments.”</strong>
              <small>You make the click.</small>
            </aside>
          </div>
        </div>
      </section>

      <section className="welcome-how" aria-labelledby="welcome-how-title">
        <div className="welcome-section-heading">
          <span>Simple by design</span>
          <h2 id="welcome-how-title">Help that feels human.</h2>
        </div>
        <div className="welcome-how__grid">
          <article>
            <span className="welcome-number">1</span>
            <h3>One next step</h3>
            <p>No long checklist. Just one large, plain-language instruction.</p>
          </article>
          <article>
            <Volume2 aria-hidden="true" size={29} />
            <h3>See it or hear it</h3>
            <p>Use larger text and optional spoken guidance at your pace.</p>
          </article>
          <article>
            <ShieldCheck aria-hidden="true" size={29} />
            <h3>Safe at every step</h3>
            <p>Nothing important is submitted until you choose the real button.</p>
          </article>
        </div>
      </section>

      <section className="welcome-choose" aria-labelledby="welcome-choose-title">
        <div>
          <span>One website, two simple spaces</span>
          <h2 id="welcome-choose-title">Where would you like to go?</h2>
        </div>
        <div className="welcome-choose__actions">
          <button className="welcome-destination welcome-destination--person" onClick={onStart} type="button">
            <span><UserRound aria-hidden="true" size={28} /></span>
            <div><strong>My tasks</strong><small>Large, simple guidance with no sign-up</small></div>
            <ArrowRight aria-hidden="true" size={24} />
          </button>
          <button className="welcome-destination" onClick={onCaregiver} type="button">
            <span><HeartHandshake aria-hidden="true" size={28} /></span>
            <div><strong>Caregiver console</strong><small>Live agent status, history, memory, and help requests</small></div>
            <ArrowRight aria-hidden="true" size={24} />
          </button>
        </div>
      </section>

      <footer className="welcome-footer">
        <span><MousePointer2 aria-hidden="true" size={19} /> WebAccessible</span>
        <p>Dignity first. The person browsing makes every click.</p>
      </footer>
    </main>
  );
}
