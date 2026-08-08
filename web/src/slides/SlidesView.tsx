import { useEffect, useMemo, useState } from "react";
import { Check, ChevronLeft, ChevronRight, Download, LoaderCircle, MonitorPlay } from "lucide-react";

const SLIDES = [
  "A browser that does the errand for you",
  "Why it exists",
  "The participant starts with a goal",
  "A visible, narrated browser run",
  "DMV demo in progress",
  "Grocery demo in progress",
  "Haircut demo in progress",
  "Where autonomy stops",
  "The caregiver console",
  "Memory and reminders",
  "The cloud stack",
  "One request. A visible run. Human control.",
] as const;

// The second deck: rebuilt from `scripts/build-slides2.py`, dark themed, and carrying a
// real screenshot of a run rather than an illustration. Served at /slides2 so the
// original deck stays exactly where anyone linked it.
const SLIDES2 = [
  "WebAccessible",
  "The web got harder exactly as it became mandatory",
  "Say the errand. Watch it happen.",
  "Mid-errand: a live run",
  "Read. Plan. Check. Narrate.",
  "Where autonomy stops",
  "The caregiver console",
  "Memory and reminders",
  "The stack",
  "One sentence. A visible run.",
] as const;

type DemoKind = "dmv" | "groceries" | "haircut";

const DEMOS: Record<DemoKind, {
  task: string;
  site: string;
  path: string;
  eyebrow: string;
  title: string;
  detail: string;
  choices: string[];
  steps: string[];
  active: string;
}> = {
  dmv: {
    task: "Get in line at the DMV",
    site: "dmv.ca.gov",
    path: "/virtual-office",
    eyebrow: "California DMV · Virtual office",
    title: "Choose a field office",
    detail: "The agent found nearby offices and is choosing the shortest current wait.",
    choices: ["Hope Street · 18 min", "Lincoln Park · 31 min", "Westminster · 44 min"],
    steps: ["Opened the DMV virtual office", "Entered the demo ZIP code", "Compared nearby wait times"],
    active: "Joining the Hope Street queue",
  },
  groceries: {
    task: "Add groceries to the cart",
    site: "instacart.com",
    path: "/store/sprouts/cart",
    eyebrow: "Sprouts · Weekly staples",
    title: "6 items in the cart",
    detail: "The agent is checking the last item and will stop before checkout.",
    choices: ["Bananas · 2 lb", "Whole milk · 1 gal", "Oatmeal · 18 oz"],
    steps: ["Opened the Sprouts storefront", "Found the usual weekly staples", "Added six requested items"],
    active: "Checking the cart for substitutions",
  },
  haircut: {
    task: "Book a haircut",
    site: "neighborhoodbarber.example",
    path: "/appointments",
    eyebrow: "Neighborhood Barber · Appointments",
    title: "Choose a time",
    detail: "The agent found the next open Saturday appointment and is holding it.",
    choices: ["Saturday · 10:30 AM", "Saturday · 11:15 AM", "Monday · 9:00 AM"],
    steps: ["Opened the booking calendar", "Selected a standard haircut", "Found the next open Saturday"],
    active: "Holding 10:30 AM for review",
  },
};

function readInitialSlide(count: number) {
  const requested = Number(new URLSearchParams(window.location.search).get("slide"));
  return Number.isInteger(requested) && requested >= 1 && requested <= count ? requested - 1 : 0;
}

function DemoProgressCapture({ kind }: { kind: DemoKind }) {
  const demo = DEMOS[kind];
  return (
    <main className={`demo-capture demo-capture--${kind}`} id="main-content">
      <header className="demo-capture__topbar">
        <div>
          <span className="demo-capture__brand">WEBACCESSIBLE</span>
          <span className="demo-capture__tag"><MonitorPlay aria-hidden="true" size={15} /> Illustrative in-progress demo</span>
        </div>
        <strong>{demo.task}</strong>
      </header>

      <div className="demo-capture__workspace">
        <section aria-label="Demo browser" className="demo-capture__browser">
          <div className="demo-capture__browser-tabs"><i /><i /><i /><span>{demo.task}</span><small>Managed</small></div>
          <div className="demo-capture__address"><span>🔒</span><strong>{demo.site}</strong>{demo.path}</div>
          <div className="demo-capture__site">
            <p>{demo.eyebrow}</p>
            <h1>{demo.title}</h1>
            <span>{demo.detail}</span>
            <div className="demo-capture__choices">
              {demo.choices.map((choice, index) => (
                <div className={index === 0 ? "selected" : ""} key={choice}>
                  <span>{choice}</span>{index === 0 ? <Check aria-hidden="true" size={20} /> : null}
                </div>
              ))}
            </div>
          </div>
        </section>

        <aside aria-label="Agent activity" className="demo-capture__activity">
          <div className="demo-capture__activity-heading">
            <span>LIVE ACTIVITY</span>
            <strong><i /> Agent working</strong>
          </div>
          <h2>What I&apos;m doing</h2>
          <ol>
            {demo.steps.map((step) => <li key={step}><Check aria-hidden="true" size={18} /><span>{step}</span></li>)}
            <li className="active"><LoaderCircle aria-hidden="true" size={18} /><span>{demo.active}</span></li>
          </ol>
          <div className="demo-capture__narration">“{demo.active}.”</div>
          <p className="demo-capture__boundary">Money, deletion, and passwords always pause for a person.</p>
        </aside>
      </div>
    </main>
  );
}

export function SlidesView() {
  const capture = window.location.pathname.match(/^\/slides\/demo\/(dmv|groceries|haircut)\/?$/)?.[1] as DemoKind | undefined;
  const second = window.location.pathname.startsWith("/slides2");
  const titles = second ? SLIDES2 : SLIDES;
  const base = second ? "/slides2/deck" : "/slides/deck";
  const [index, setIndex] = useState(() => readInitialSlide(second ? SLIDES2.length : SLIDES.length));

  const image = useMemo(() => `${base}/slide-${String(index + 1).padStart(2, "0")}.png`, [base, index]);

  useEffect(() => {
    if (capture) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") setIndex((current) => Math.max(0, current - 1));
      if (event.key === "ArrowRight" || event.key === " ") setIndex((current) => Math.min(titles.length - 1, current + 1));
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [capture, titles.length]);

  useEffect(() => {
    if (capture) return;
    const url = new URL(window.location.href);
    url.searchParams.set("slide", String(index + 1));
    window.history.replaceState({}, "", url);
  }, [capture, index]);

  if (capture) return <DemoProgressCapture kind={capture} />;

  return (
    <main className="slides-view" id="main-content">
      <header className="slides-view__toolbar">
        <div className="slides-view__identity">
          <span className="slides-view__mark">WA</span>
          <div><strong>WebAccessible</strong><span>{second ? "Application overview · deck two" : "Application overview · unlisted"}</span></div>
        </div>
        {second ? null : (
          <a className="slides-view__download" download href="/slides/WebAccessible-Application-Overview.pptx">
            <Download aria-hidden="true" size={18} /> Download PowerPoint
          </a>
        )}
      </header>

      <div className="slides-view__workspace">
        <aside aria-label="Slides" className="slides-view__rail">
          {titles.map((title, slideIndex) => (
            <button
              aria-label={`Slide ${slideIndex + 1}: ${title}`}
              aria-current={slideIndex === index ? "page" : undefined}
              className={slideIndex === index ? "active" : ""}
              key={title}
              onClick={() => setIndex(slideIndex)}
              type="button"
            >
              <span>{slideIndex + 1}</span>
              <img alt="" loading={slideIndex < 3 ? "eager" : "lazy"} src={`${base}/slide-${String(slideIndex + 1).padStart(2, "0")}.png`} />
            </button>
          ))}
        </aside>

        <section aria-label={`Slide ${index + 1}: ${titles[index]}`} className="slides-view__stage">
          <div className="slides-view__canvas"><img alt={`Slide ${index + 1}: ${titles[index]}`} src={image} /></div>
          <div className="slides-view__controls">
            <button aria-label="Previous slide" disabled={index === 0} onClick={() => setIndex((current) => current - 1)} type="button"><ChevronLeft aria-hidden="true" size={22} /></button>
            <span><strong>{index + 1}</strong> / {titles.length}</span>
            <button aria-label="Next slide" disabled={index === titles.length - 1} onClick={() => setIndex((current) => current + 1)} type="button"><ChevronRight aria-hidden="true" size={22} /></button>
          </div>
        </section>
      </div>
    </main>
  );
}
