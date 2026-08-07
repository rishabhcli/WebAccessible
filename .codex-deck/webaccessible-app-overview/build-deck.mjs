import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";
import { buildSlide02 } from "./slide-02.mjs";
import { buildSlide06 } from "./slide-06.mjs";
import { buildSlide10 } from "./slide-10.mjs";
import { buildSlide13 } from "./slide-13.mjs";
import { buildSlide17 } from "./slide-17.mjs";
import { buildSlide26 } from "./slide-26.mjs";

const TMP_DIR = "C:/Users/might/OneDrive/Documents/GitHub/WebAccessible/.codex-deck/webaccessible-app-overview";
const FINAL_PPTX = "C:/Users/might/OneDrive/Documents/GitHub/WebAccessible/artifacts/WebAccessible-Application-Overview.pptx";
const ASSETS = path.join(TMP_DIR, "assets");
const RENDER_DIR = path.join(TMP_DIR, "rendered");

const INK = "#17201B";
const MUTED = "#55635B";
const GREEN = "#176847";
const GREEN_DARK = "#173F32";
const GREEN_SOFT = "#E7F0EB";
const RULE = "#C8D1CA";
const WHITE = "#FFFFFF";

function paragraph(text, fontSize, { bold = false, color = INK, spaceAfter = 0 } = {}) {
  return {
    runs: [{ run: text, textStyle: { fontSize: `${fontSize}px`, typeface: "Arial", color, bold } }],
    ...(spaceAfter ? { spaceAfter } : {}),
    paragraphStyle: { lineSpacingPercent: 100000 },
  };
}

function pair(title, body) {
  return {
    titleHere: paragraph(title, 32, { bold: true, color: GREEN_DARK, spaceAfter: 700 }),
    loremIpsumDolorSitAmetConsecteturAdipiscing: paragraph(body, 22, { color: MUTED }),
  };
}

function architecturePair(title, body) {
  return {
    titleHere: paragraph(title, 27, { bold: true, color: GREEN_DARK, spaceAfter: 700 }),
    loremIpsumDolorSitAmetConsecteturAdipiscing: paragraph(body, 20, { color: MUTED }),
  };
}

function gridPair(title, body) {
  return {
    titleGoesHere: paragraph(title, 32, { bold: true, color: GREEN_DARK, spaceAfter: 650 }),
    loremIpsumDolorSitAmetConsecteturAdipiscing: paragraph(body, 21, { color: MUTED }),
  };
}

async function readImage(name) {
  const bytes = await fs.readFile(path.join(ASSETS, name));
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

async function writeBlob(filePath, blob) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

function addText(slide, name, text, position, style = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name,
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    typeface: "Arial",
    fontSize: style.fontSize ?? 24,
    bold: style.bold ?? false,
    color: style.color ?? INK,
    alignment: style.alignment ?? "left",
    verticalAlignment: style.verticalAlignment ?? "top",
  };
  return shape;
}

function addPageNumber(slide, page) {
  addText(slide, `page-${page}`, String(page).padStart(2, "0"), { left: 1186, top: 662, width: 52, height: 22 }, {
    fontSize: 13,
    color: MUTED,
    alignment: "right",
  });
}

function addNotes(slide, lines) {
  slide.speakerNotes.textFrame.setText(`[Sources]\n${lines.map((line) => `- ${line}`).join("\n")}`);
}

function addScreenshotSlide(presentation, { page, title, subtitle, imageBytes, alt }) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  slide.shapes.add({
    geometry: "rect",
    name: `accent-${page}`,
    position: { left: 41, top: 36, width: 10, height: 62 },
    fill: GREEN,
    line: { style: "solid", fill: GREEN, width: 0 },
  });
  addText(slide, `title-${page}`, title, { left: 69, top: 34, width: 1169, height: 80 }, {
    fontSize: 44,
    bold: true,
    color: INK,
  });
  addText(slide, `subtitle-${page}`, subtitle, { left: 69, top: 126, width: 1130, height: 58 }, {
    fontSize: 22,
    color: MUTED,
  });
  slide.shapes.add({
    geometry: "roundRect",
    name: `image-backing-${page}`,
    position: { left: 72, top: 196, width: 1136, height: 464 },
    fill: GREEN_SOFT,
    line: { style: "solid", fill: RULE, width: 1 },
    borderRadius: 18,
  });
  slide.images.add({
    blob: imageBytes,
    contentType: "image/png",
    alt,
    fit: "cover",
    crop: { left: 0, top: 0, right: 0, bottom: 0.22 },
    geometry: "roundRect",
    borderRadius: 16,
    position: { left: 80, top: 204, width: 1120, height: 448 },
  });
  addPageNumber(slide, page);
  return slide;
}

function addDemoScreenshotSlide(presentation, { page, title, subtitle, imageBytes, alt }) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  slide.shapes.add({
    geometry: "rect",
    name: `demo-accent-${page}`,
    position: { left: 41, top: 28, width: 10, height: 58 },
    fill: GREEN,
    line: { style: "solid", fill: GREEN, width: 0 },
  });
  addText(slide, `demo-title-${page}`, title, { left: 69, top: 26, width: 1169, height: 54 }, {
    fontSize: 40,
    bold: true,
    color: INK,
  });
  addText(slide, `demo-subtitle-${page}`, subtitle, { left: 69, top: 88, width: 1130, height: 36 }, {
    fontSize: 19,
    color: MUTED,
  });
  slide.shapes.add({
    geometry: "roundRect",
    name: `demo-image-backing-${page}`,
    position: { left: 147, top: 138, width: 986, height: 555 },
    fill: GREEN_SOFT,
    line: { style: "solid", fill: RULE, width: 1 },
    borderRadius: 16,
  });
  slide.images.add({
    blob: imageBytes,
    contentType: "image/png",
    alt,
    fit: "contain",
    geometry: "roundRect",
    borderRadius: 14,
    position: { left: 155, top: 146, width: 970, height: 546 },
  });
  addPageNumber(slide, page);
  return slide;
}

async function main() {
  await fs.mkdir(RENDER_DIR, { recursive: true });
  await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });

  const landing = await readImage("landing.png");
  const participant = await readImage("participant.png");
  const caregiver = await readImage("caregiver.png");
  const demoDmv = await readImage("demo-dmv.png");
  const demoGroceries = await readImage("demo-groceries.png");
  const demoHaircut = await readImage("demo-haircut.png");

  const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });

  // 1 — Cover, adapted from Codex Grid slide 08.
  {
    const slide = presentation.slides.add();
    slide.background.fill = WHITE;
    addText(slide, "cover-eyebrow", "WEBACCESSIBLE", { left: 42, top: 38, width: 500, height: 32 }, {
      fontSize: 18,
      bold: true,
      color: GREEN,
    });
    addText(slide, "cover-title", "A browser that\ndoes the errand\nfor you.", { left: 42, top: 146, width: 570, height: 214 }, {
      fontSize: 58,
      bold: true,
      color: GREEN_DARK,
    });
    addText(slide, "cover-subtitle", "Plain-language autonomous browsing for older adults — with caregiver visibility and hard safety stops.", { left: 42, top: 382, width: 540, height: 126 }, {
      fontSize: 26,
      color: MUTED,
    });
    addText(slide, "cover-version", "Application overview · 2026", { left: 42, top: 596, width: 420, height: 30 }, {
      fontSize: 18,
      color: GREEN,
      bold: true,
    });
    slide.shapes.add({
      geometry: "roundRect",
      name: "cover-image-backing",
      position: { left: 658, top: 42, width: 582, height: 588 },
      fill: GREEN_SOFT,
      line: { style: "solid", fill: RULE, width: 1 },
      borderRadius: 20,
    });
    slide.images.add({
      blob: landing,
      contentType: "image/png",
      alt: "WebAccessible landing page showing a water-bill task preview",
      fit: "cover",
      crop: { left: 0.42, top: 0, right: 0.02, bottom: 0 },
      geometry: "roundRect",
      borderRadius: 18,
      position: { left: 666, top: 50, width: 566, height: 572 },
    });
    addPageNumber(slide, 1);
    addNotes(slide, [
      "README.md and AGENTS.md at repository revision 64fc387.",
      "Screenshot: locally built WebAccessible landing page, http://127.0.0.1:8000/.",
    ]);
  }

  // 2 — Problem statement, Codex Grid slide 02.
  {
    const slide = buildSlide02(presentation, {
      title: paragraph("WHY IT EXISTS", 22, { bold: true, color: GREEN }),
      title2: paragraph("A DIFFERENT BROWSER", 22, { bold: true, color: MUTED }),
      title3: paragraph("Older adults should not need perfect recall — or a distant relative — to finish an online errand.", 72, { bold: true, color: GREEN_DARK }),
    });
    addNotes(slide, [
      "README.md, opening problem statement and intended user.",
      "AGENTS.md, current autonomous execution model.",
    ]);
  }

  // 3 — Participant launcher.
  {
    const slide = addScreenshotSlide(presentation, {
      page: 3,
      title: "The participant starts with a goal — not setup.",
      subtitle: "Three ready errands, a free-form request, and grounded recall — all behind passwordless entry.",
      imageBytes: participant,
      alt: "WebAccessible participant task launcher with DMV, grocery, and haircut errands",
    });
    addNotes(slide, [
      "README.md, ‘What it looks like to use’ and passwordless entry.",
      "web/src/agent/TaskLauncher.tsx at repository revision 64fc387.",
      "Screenshot: locally built participant view, http://127.0.0.1:8000/participant.",
    ]);
  }

  // 4 — Agent flow, Codex Grid slide 17.
  {
    const slide = buildSlide17(presentation, {
      title: paragraph("One request becomes a visible, narrated browser run.", 48, { bold: true, color: INK }),
      label1: paragraph("ASK", 18, { bold: true, color: GREEN }),
      label2: paragraph("WATCH", 18, { bold: true, color: GREEN }),
      label3: paragraph("DECIDE", 18, { bold: true, color: GREEN }),
      body1: pair("Say the errand", "Choose a ready task or describe it in your own words."),
      body2: pair("The agent works", "It drives a real browser and narrates each action in plain language."),
      body3: pair("People keep control", "Money, deletion, and passwords stop the run for a person."),
      footer1: "04",
    });
    addNotes(slide, [
      "README.md, participant workflow and visible action narration.",
      "AGENTS.md, execution and human-decision boundaries.",
      "web/src/agent/AgentDashboard.tsx and StepsPanel.tsx at repository revision 64fc387.",
    ]);
  }

  // 5 — Curated DMV demo in progress.
  {
    const slide = addDemoScreenshotSlide(presentation, {
      page: 5,
      title: "Demo: joining the shortest DMV queue.",
      subtitle: "The work stays visible: completed steps, current action, and the safety boundary share one screen.",
      imageBytes: demoDmv,
      alt: "Illustrative WebAccessible DMV task in progress, comparing field-office wait times",
    });
    addNotes(slide, [
      "web/src/slides/SlidesView.tsx at repository revision 64fc387 plus working-tree presentation additions.",
      "Screenshot: local illustrative in-progress view, http://127.0.0.1:8000/slides/demo/dmv.",
      "This is an illustrative UI state, not live Browserbase execution evidence; local Browserbase readiness was unavailable during capture.",
    ]);
  }

  // 6 — Curated grocery demo in progress.
  {
    const slide = addDemoScreenshotSlide(presentation, {
      page: 6,
      title: "Demo: reviewing the cart before checkout.",
      subtitle: "The agent completes reversible work, then leaves the purchase decision to the person.",
      imageBytes: demoGroceries,
      alt: "Illustrative WebAccessible grocery task in progress, reviewing an Instacart cart",
    });
    addNotes(slide, [
      "web/src/slides/SlidesView.tsx at repository revision 64fc387 plus working-tree presentation additions.",
      "Screenshot: local illustrative in-progress view, http://127.0.0.1:8000/slides/demo/groceries.",
      "This is an illustrative UI state, not live Browserbase execution evidence; local Browserbase readiness was unavailable during capture.",
    ]);
  }

  // 7 — Curated haircut demo in progress.
  {
    const slide = addDemoScreenshotSlide(presentation, {
      page: 7,
      title: "Demo: holding the next practical haircut time.",
      subtitle: "Plain-language narration makes the run understandable without exposing browser internals.",
      imageBytes: demoHaircut,
      alt: "Illustrative WebAccessible haircut task in progress, holding a Saturday appointment",
    });
    addNotes(slide, [
      "web/src/slides/SlidesView.tsx at repository revision 64fc387 plus working-tree presentation additions.",
      "Screenshot: local illustrative in-progress view, http://127.0.0.1:8000/slides/demo/haircut.",
      "This is an illustrative UI state, not live Browserbase execution evidence; local Browserbase readiness was unavailable during capture.",
    ]);
  }

  // 8 — Safety, Codex Grid slide 10.
  {
    const slide = buildSlide10(presentation, {
      title: paragraph("Autonomy stops exactly where consequences begin.", 48, { bold: true, color: INK }),
      body1: paragraph("Reversible work continues without constant interruptions.", 32, { bold: true, color: GREEN_DARK }),
      body2: {
        loremIpsumDolorSitAmetConsecteturAdipiscing: paragraph("The agent may search, navigate, fill forms, add to a cart, join a queue, or hold an appointment.", 23, { color: MUTED, spaceAfter: 900 }),
        loremIpsumDolorSitAmetConsecteturAdipiscing2: paragraph("It does not hide uncertainty: risky actions pause and failures remain visible.", 23, { color: MUTED }),
      },
      label1: paragraph("Money pauses", 30, { bold: true, color: GREEN_DARK }),
      label2: paragraph("Deletion pauses", 30, { bold: true, color: GREEN_DARK }),
      label3: paragraph("Passwords stay private", 30, { bold: true, color: GREEN_DARK }),
      label4: paragraph("Every action is visible", 30, { bold: true, color: GREEN_DARK }),
      label5: paragraph("Scam signals escalate", 30, { bold: true, color: GREEN_DARK }),
      footer1: "08",
    });
    addNotes(slide, [
      "README.md, ‘What it will not do’.",
      "AGENTS.md, autonomy boundaries, password handling, and scam escalation.",
    ]);
  }

  // 9 — Caregiver console.
  {
    const slide = addScreenshotSlide(presentation, {
      page: 9,
      title: "Caregivers see evidence — not remote controls.",
      subtitle: "Run history, cost, routines, notes, and cloud readiness — without exposing provider keys.",
      imageBytes: caregiver,
      alt: "WebAccessible caregiver console showing Browserbase, EverOS, Snowflake, and Cortex status",
    });
    addNotes(slide, [
      "README.md, caregiver view and architecture sections.",
      "web/src/caregiver/CaregiverView.tsx at repository revision 64fc387.",
      "Screenshot: locally built caregiver console, http://127.0.0.1:8000/caregiver.",
      "The screenshot truthfully shows Browserbase requiring attention while EverOS, Snowflake, and Cortex are connected.",
    ]);
  }

  // 10 — Memory, Codex Grid slide 13.
  {
    const slide = buildSlide13(presentation, {
      title: paragraph("Memory turns completed errands into dependable context.", 48, { bold: true, color: INK }),
      body1: gridPair("Grounded recall", "Answers come from completed runs. If the record is missing, the app says so."),
      body2: gridPair("Routine timing", "Repeated task starts can reveal daily, weekly, or monthly patterns."),
      body3: gridPair("Proactive, not pushy", "Suggestions are dismissible, expire on their own, and avoid repeated nagging."),
      body4: gridPair("Permission first", "Accepting a reminder is the boundary that permits a new run to begin."),
      footer1: "10",
    });
    addNotes(slide, [
      "README.md, ‘It remembers what you did’.",
      "AGENTS.md, reminder consent, delivery, dismissal, and lapse behavior.",
      "backend/app/services/recall.py and proactive.py at repository revision 64fc387.",
    ]);
  }

  // 11 — Sponsor architecture, Codex Grid slide 06.
  {
    const slide = buildSlide06(presentation, {
      title: paragraph("The cloud stack separates execution, memory, and evidence.", 48, { bold: true, color: INK }),
      body1: architecturePair("Browserbase", "Managed Chrome execution with a participant-visible Live View and server-side CDP control."),
      body2: architecturePair("EverOS", "Durable episodes, readable routines, and user-owned context for recall and suggestions."),
      body3: architecturePair("Snowflake + Cortex", "Planning for cold runs, synchronized telemetry, and cost evidence from actual usage."),
      footer1: "11",
    });
    addNotes(slide, [
      "README.md, architecture and provider responsibility map.",
      "AGENTS.md and docs/sponsors/BROWSERBASE.md, execution-provider constraints.",
      "SPONSORS.md at repository revision 64fc387.",
    ]);
  }

  // 12 — Close, Codex Grid slide 26.
  {
    const slide = buildSlide26(presentation, {
      title: paragraph("THE IDEA", 22, { bold: true, color: GREEN }),
      title2: paragraph("One request.\nA visible run.\nHuman control.", 76, { bold: true, color: GREEN_DARK }),
      title3: {
        loremIpsumDetails: paragraph("No participant login", 24, { color: INK }),
        loremIpsumDetails2: paragraph("Caregiver sees the record", 24, { color: INK }),
        loremIpsumDetails3: paragraph("Safety pauses stay human", 24, { color: INK }),
      },
    });
    addNotes(slide, [
      "README.md and AGENTS.md at repository revision 64fc387.",
    ]);
  }

  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    await writeBlob(path.join(RENDER_DIR, `${stem}.png`), await presentation.export({ slide, format: "png", scale: 1 }));
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(RENDER_DIR, `${stem}.layout.json`), await layout.text());
  }

  await writeBlob(path.join(TMP_DIR, "deck-montage.webp"), await presentation.export({ format: "webp", montage: true, scale: 1 }));
  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(FINAL_PPTX);
  console.log(FINAL_PPTX);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
