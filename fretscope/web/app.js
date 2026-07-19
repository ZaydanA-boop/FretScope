/* FretScope dashboard. Vanilla JS, polls the job API. */

"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  jobs: [],
  selected: null,
  pollTimer: null,
  pollTick: 0,
  report: null,        // report of the currently displayed job
  reportJobId: null,
  renderedKey: null,   // job.id + status of the last fully rendered report
  segment: -1,         // -1 = whole song, else tone-timeline section index
  recorder: null,
  recTimer: null,
};

function toast(msg, kind) {
  const box = document.createElement("div");
  box.className = "toast" + (kind === "err" ? " err" : "");
  box.textContent = msg;
  $("toasts").appendChild(box);
  setTimeout(() => box.remove(), 4200);
}

/* ---------- sidebar collapse ---------- */

const layout = $("layout");
if (localStorage.getItem("fs-rack-hidden") === "1") {
  layout.classList.add("rack-hidden");
}
$("rack-toggle").addEventListener("click", () => {
  layout.classList.toggle("rack-hidden");
  localStorage.setItem("fs-rack-hidden",
    layout.classList.contains("rack-hidden") ? "1" : "0");
});

function relTime(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/* ---------- api ---------- */

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) { /* keep */ }
    throw new Error(detail);
  }
  return res.json();
}

/* ---------- health ---------- */

async function refreshHealth() {
  // quiet by default: chips appear only when something is actually broken
  try {
    const h = await api("/api/health");
    const warnings = [];
    if (!h.ffmpeg) warnings.push("ffmpeg missing");
    if (!h.separation_available) warnings.push("separation off");
    if (!h.model_available) warnings.push("no tone model");
    $("health").innerHTML = warnings.map((w) =>
      `<span class="chip off">${w}</span>`).join("");
  } catch (e) {
    $("health").innerHTML = '<span class="chip off">server unreachable</span>';
  }
}

/* ---------- submit ---------- */

$("submit-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const source = $("source").value.trim();
  const errEl = $("submit-error");
  errEl.hidden = true;
  if (!source) return;
  $("submit-btn").disabled = true;
  try {
    const job = await api("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source,
        use_separation: $("use-separation").checked,
      }),
    });
    $("source").value = "";
    state.selected = job.id;
    toast(`Queued: ${job.title || job.source}`);
    await refreshJobs();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.hidden = false;
  } finally {
    $("submit-btn").disabled = false;
  }
});

/* ---------- file upload (drag-drop + browse) ---------- */

async function uploadFile(file) {
  const errEl = $("submit-error");
  errEl.hidden = true;
  $("submit-btn").disabled = true;
  try {
    const form = new FormData();
    form.append("audio", file, file.name);
    form.append("use_separation", String($("use-separation").checked));
    const res = await fetch("/api/jobs/upload", { method: "POST", body: form });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (e) { /* keep */ }
      throw new Error(detail);
    }
    const job = await res.json();
    state.selected = job.id;
    toast(`Queued: ${job.title}`);
    await refreshJobs();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.hidden = false;
    toast(e.message, "err");
  } finally {
    $("submit-btn").disabled = false;
  }
}

const dropzone = $("dropzone");
$("browse-btn").addEventListener("click", () => $("upload-file").click());
$("upload-file").addEventListener("change", (ev) => {
  const file = ev.target.files[0];
  if (file) uploadFile(file);
  ev.target.value = "";
});
for (const evName of ["dragenter", "dragover"]) {
  dropzone.addEventListener(evName, (ev) => {
    ev.preventDefault();
    dropzone.classList.add("drag");
  });
}
for (const evName of ["dragleave", "drop"]) {
  dropzone.addEventListener(evName, (ev) => {
    ev.preventDefault();
    dropzone.classList.remove("drag");
  });
}
dropzone.addEventListener("drop", (ev) => {
  const file = ev.dataTransfer.files && ev.dataTransfer.files[0];
  if (file) uploadFile(file);
});

/* ---------- job list ---------- */

function statusLabel(job) {
  if (job.status === "running") {
    const st = job.stages[job.stages.length - 1];
    return st ? st.stage : "starting";
  }
  return job.status;
}

function renderJobs() {
  const ul = $("joblist");
  ul.querySelectorAll(".jobcard").forEach((n) => n.remove());
  $("joblist-empty").hidden = state.jobs.length > 0;

  for (const job of state.jobs) {
    const li = document.createElement("li");
    li.className = "jobcard" + (job.id === state.selected ? " selected" : "");
    li.innerHTML = `
      <span class="dot ${job.status}"></span>
      <span class="jobmeta">
        <span class="jobtitle"></span>
        <span class="jobsub"></span>
      </span>
      <button class="del" title="delete this analysis" aria-label="delete">&times;</button>`;
    li.querySelector(".jobtitle").textContent = job.title || job.source;
    const when = relTime(job.finished_at || job.created_at);
    li.querySelector(".jobsub").textContent =
      statusLabel(job) + (when ? ` · ${when}` : "");
    li.addEventListener("click", () => { state.selected = job.id; render(); });
    li.querySelector(".del").addEventListener("click", async (ev) => {
      ev.stopPropagation();
      try {
        await api(`/api/jobs/${job.id}`, { method: "DELETE" });
        if (state.selected === job.id) state.selected = null;
        toast("Analysis deleted");
        await refreshJobs();
      } catch (e) {
        toast("Can't delete while the job is running", "err");
      }
    });
    ul.appendChild(li);
  }
}

/* ---------- stage views ---------- */

function show(view) {
  for (const id of ["stage-empty", "progress-view", "report-view", "error-view"]) {
    $(id).hidden = id !== view;
  }
  // section tabs only make sense while a report is on screen
  $("section-tabs").hidden = view !== "report-view";
}

const STAGE_ORDER = ["download", "decode", "separation", "classify", "transcribe", "tone"];
const STAGE_NAMES = {
  download: "Fetch", decode: "Decode", separation: "Isolate guitar",
  classify: "Classify part", transcribe: "Transcribe", tone: "Analyze tone",
};

function renderProgress(job) {
  $("progress-title").textContent = job.title || job.source;
  const ol = $("stagelog");
  ol.innerHTML = "";
  const byStage = Object.fromEntries(job.stages.map((s) => [s.stage, s]));
  for (const key of STAGE_ORDER) {
    const s = byStage[key];
    const li = document.createElement("li");
    li.className = s ? s.status : "";
    const ico = !s ? "&nbsp;" : s.status === "done" ? "&#10003;"
      : s.status === "failed" ? "&#10007;" : "&#9679;";
    li.innerHTML = `<span class="st-ico">${ico}</span>
      <span class="st-name">${STAGE_NAMES[key] || key}</span>
      <span class="st-detail"></span>`;
    li.querySelector(".st-detail").textContent = s ? (s.detail || "") : "";
    ol.appendChild(li);
  }
  show("progress-view");
}

function esc(s) {
  const d = document.createElement("span");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function renderReport(job, report) {
  $("report-title").textContent = report.meta.title || job.title || job.source;
  const sub = $("report-sub");
  if (report.meta.webpage_url) {
    sub.innerHTML = `${esc(report.meta.uploader || "")} &nbsp;
      <a href="${esc(report.meta.webpage_url)}" target="_blank" rel="noopener">open on YouTube</a>`;
  } else {
    sub.textContent = report.meta.source || "";
  }

  // stem player: only touch src when it actually changes, or playback resets
  const hasStem = report.separation && report.separation.separated;
  $("player-wrap").hidden = !hasStem;
  if (hasStem) {
    const src = `/api/jobs/${job.id}/stem`;
    const audio = $("stem-audio");
    if (!audio.src.endsWith(src)) audio.src = src;
  }

  // separation banner
  const sep = report.separation;
  $("separation-banner").textContent = sep
    ? (sep.separated
        ? `Guitar isolated with ${sep.method}. ${sep.notes[0] || ""}`
        : `Heads up: ${sep.notes[0] || "analysis ran on the full mix."}`)
    : "";

  // song facts: key / tempo / tuning as friendly chips
  const facts = report.facts || {};
  const factsEl = $("facts");
  factsEl.innerHTML = "";
  if (facts.key) {
    const tuning = facts.tuning_cents || 0;
    const tuningTxt = Math.abs(tuning) < 15 ? "standard"
      : `${Math.abs(tuning).toFixed(0)} cents ${tuning > 0 ? "sharp" : "flat"}`;
    const items = [
      ["Key", facts.key],
      ["Tempo", `~${Math.round(facts.tempo_bpm || 0)} BPM`],
      ["Tuning", tuningTxt],
    ];
    factsEl.innerHTML = items.map(([k, v]) =>
      `<span class="fact">${esc(k)} <b>${esc(v)}</b></span>`).join("");
    factsEl.title = "Best guesses from the audio: key can be confused by key " +
      "changes, tempo by half/double-time feels.";
  }

  // transcription: tab shown in full; chord charts appear as chord diagrams
  // with the bulky timed chart tucked behind a toggle
  const tr = report.transcription || {};
  const heading = $("transcription-heading");
  const body = $("transcription-body");
  const note = $("classification-note");
  const diagrams = $("chord-diagrams");
  const ribbonWrap = $("ribbon-wrap");
  body.hidden = false;
  diagrams.innerHTML = "";
  ribbonWrap.hidden = true;
  if (tr.kind === "lead") {
    heading.textContent = "Tab";
    body.textContent = tr.tab || "(empty)";
    note.textContent = "This part plays one note at a time, so you get a tab. " +
      "It's one comfortable way to play it, not the only way.";
    note.title = tr.classification?.rationale || "";
  } else if (tr.kind === "rhythm") {
    heading.textContent = "Chords";
    body.hidden = true;
    body.textContent = "";
    const chords = (tr.chords || []).filter((c) => c.chord !== "N");
    const dur = {};
    for (const c of chords) dur[c.chord] = (dur[c.chord] || 0) + (c.end - c.start);
    const total = Object.values(dur).reduce((a, b) => a + b, 0) || 1;
    const top = Object.entries(dur).sort((a, b) => b[1] - a[1]).slice(0, 5);
    note.textContent = "This part strums chords. Here's what it leans on:";
    note.title = tr.classification?.rationale || "";
    renderChordDiagrams(diagrams, top, total);
    renderChordRibbon(tr.chords || []);
  } else {
    heading.textContent = "Transcription";
    body.textContent = "Unavailable: " + (tr.error || "unknown failure");
    note.textContent = "";
  }

  // lyrics with chords (only present when a vocals stem existed and whisper ran)
  const lyr = report.lyrics || {};
  const lyricsBox = $("lyrics");
  lyricsBox.hidden = !(lyr.lines && lyr.lines.length);
  if (lyr.lines && lyr.lines.length) {
    $("lyrics-note").textContent = lyr.note || "";
    const wrap = $("lyrics-lines");
    wrap.innerHTML = "";
    for (const line of lyr.lines) {
      const div = document.createElement("div");
      div.className = "lyric-line";
      div.innerHTML = `<span class="lyric-chord">${esc(line.chord || "")}</span>
        <span class="lyric-text">${esc(line.text)}</span>`;
      div.title = `${fmtTime(line.start)} - ${fmtTime(line.end)}`;
      div.addEventListener("click", () => {
        const audio = $("stem-audio");
        if (audio.src) { audio.currentTime = line.start; audio.play(); }
      });
      wrap.appendChild(div);
    }
  }

  // switching songs: reset scope and clear the previous song's match results
  if (state.reportJobId !== job.id) {
    state.segment = -1;
    $("advice-list").innerHTML = "";
    $("match-caveat").hidden = true;
    $("match-error").hidden = true;
  }
  state.report = report;
  state.reportJobId = job.id;
  renderTimeline(report);
  renderToneScope();

  // measurements, labeled for humans; the technical meaning rides in tooltips
  const f = (report.tone || {}).features || {};
  const dl = $("measurements");
  dl.innerHTML = "";
  const rows = [
    ["loudness", f.rms_db != null ? f.rms_db + " dB" : null,
     "average level of the track (RMS)"],
    ["spikiness", f.crest_db != null ? f.crest_db + " dB" : null,
     "gap between the loudest peaks and the average; low = squashed by " +
     "compression or distortion (crest factor)"],
    ["clipping", f.flat_top_ratio,
     "how often the waveform slams into its ceiling; distortion literally " +
     "flattens the wave tops"],
    ["extra harmonics", f.harmonic_distortion,
     "overtone energy versus the note itself; drive pedals add overtones"],
    ["brightness", f.spectral_centroid_hz != null
     ? Math.round(f.spectral_centroid_hz) + " Hz" : null,
     "where the energy sits: higher = brighter tone (spectral centroid)"],
    ["dark ↔ bright lean", f.tilt_db_per_octave != null
     ? f.tilt_db_per_octave + " dB/oct" : null,
     "negative leans dark/warm, closer to zero leans bright (spectral tilt)"],
    ["ring-out time", f.decay_t60_s != null ? f.decay_t60_s + " s" : null,
     "how long sound takes to fade after notes stop; long = reverb or big sustain"],
    ["dynamics", f.dynamic_range_db != null ? f.dynamic_range_db + " dB" : null,
     "spread between loud and quiet moments"],
  ];
  for (const [k, v, hint] of rows) {
    if (v == null) continue;
    const div = document.createElement("div");
    div.title = hint;
    div.innerHTML = `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`;
    dl.appendChild(div);
  }

  // limitations
  const ul = $("limitations");
  ul.innerHTML = "";
  for (const lim of report.limitations || []) {
    const li = document.createElement("li");
    li.textContent = lim;
    ul.appendChild(li);
  }

  show("report-view");
}

/* ---------- chord diagrams ---------- */

// Hand shapes for the everyday chords, frets low E → high e (-1 = don't play).
const OPEN_SHAPES = {
  "C": [-1, 3, 2, 0, 1, 0], "A": [-1, 0, 2, 2, 2, 0], "G": [3, 2, 0, 0, 0, 3],
  "E": [0, 2, 2, 1, 0, 0], "D": [-1, -1, 0, 2, 3, 2], "F": [-1, -1, 3, 2, 1, 1],
  "Am": [-1, 0, 2, 2, 1, 0], "Em": [0, 2, 2, 0, 0, 0], "Dm": [-1, -1, 0, 2, 3, 1],
  "A7": [-1, 0, 2, 0, 2, 0], "B7": [-1, 2, 1, 2, 0, 2], "C7": [-1, 3, 2, 3, 1, 0],
  "D7": [-1, -1, 0, 2, 1, 2], "E7": [0, 2, 0, 1, 0, 0], "G7": [3, 2, 0, 0, 0, 1],
  "Am7": [-1, 0, 2, 0, 1, 0], "Dm7": [-1, -1, 0, 2, 1, 1], "Em7": [0, 2, 0, 0, 0, 0],
  "Cmaj7": [-1, 3, 2, 0, 0, 0], "Amaj7": [-1, 0, 2, 1, 2, 0],
  "Dmaj7": [-1, -1, 0, 2, 2, 2], "Fmaj7": [-1, -1, 3, 2, 1, 0],
  "Gmaj7": [3, 2, 0, 0, 0, 2],
};

const PC_INDEX = { "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
                   "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11 };

// Movable barre templates (offset added to every non-negative fret; 0 = the barre)
const BARRE = {
  "E":  { "": [0, 2, 2, 1, 0, 0], "m": [0, 2, 2, 0, 0, 0],
          "7": [0, 2, 0, 1, 0, 0], "m7": [0, 2, 0, 0, 0, 0] },
  "A":  { "": [-1, 0, 2, 2, 2, 0], "m": [-1, 0, 2, 2, 1, 0],
          "7": [-1, 0, 2, 0, 2, 0], "m7": [-1, 0, 2, 0, 1, 0],
          "maj7": [-1, 0, 2, 1, 2, 0] },
};

function chordShape(label) {
  if (OPEN_SHAPES[label]) return { frets: OPEN_SHAPES[label], base: 1 };
  const m = label.match(/^([A-G]#?)(maj7|m7|m|7)?$/);
  if (!m) return null;
  const pc = PC_INDEX[m[1]];
  const quality = m[2] || "";
  const fE = ((pc - 4) % 12 + 12) % 12 || 12;   // barre fret on the E string
  const fA = ((pc - 9) % 12 + 12) % 12 || 12;   // barre fret on the A string
  const candidates = [];
  if (BARRE.E[quality]) candidates.push({ f: fE, tpl: BARRE.E[quality] });
  if (BARRE.A[quality]) candidates.push({ f: fA, tpl: BARRE.A[quality] });
  if (!candidates.length) return null;
  candidates.sort((a, b) => a.f - b.f);
  const { f, tpl } = candidates[0];
  return { frets: tpl.map((v) => (v < 0 ? -1 : v + f)), base: f };
}

function chordSVG(shape) {
  const { frets, base } = shape;
  const left = 16, top = 24, w = 62, h = 80, cols = 5, rows = 5;
  const sx = (i) => left + (i * w) / cols;   // string x (0..5)
  const fy = (i) => top + (i * h) / rows;    // fret line y (0..5)
  let s = "";
  // strings and fret lines
  for (let i = 0; i <= 5; i++) {
    s += `<line class="cd-grid" x1="${sx(i)}" y1="${top}" x2="${sx(i)}" y2="${top + h}"/>`;
  }
  for (let i = 0; i <= rows; i++) {
    s += `<line class="cd-grid" x1="${left}" y1="${fy(i)}" x2="${left + w}" y2="${fy(i)}"/>`;
  }
  if (base === 1) {
    s += `<line class="cd-nut" x1="${left - 1}" y1="${top}" x2="${left + w + 1}" y2="${top}"/>`;
  } else {
    // position label in its own right-side gutter, clear of dots and grid
    s += `<text class="cd-basefret" x="${left + w + 9}" y="${fy(1) - h / rows / 2 + 3}"
            text-anchor="start">${base}fr</text>`;
  }
  // finger numbering: lowest frets first, barres get one finger
  const fretted = frets.map((f, i) => ({ f, i })).filter((o) => o.f > 0);
  const byFret = {};
  for (const o of fretted) (byFret[o.f] = byFret[o.f] || []).push(o.i);
  let next = 1;
  const fingerOf = {};
  for (const f of Object.keys(byFret).map(Number).sort((a, b) => a - b)) {
    const strings = byFret[f];
    if (strings.length >= 3 && next === 1) {           // barre
      for (const i of strings) fingerOf[i] = 1;
      next = 2;
    } else {
      for (const i of strings.sort((a, b) => a - b)) {
        fingerOf[i] = Math.min(next, 4);
        next += 1;
      }
    }
  }
  frets.forEach((f, i) => {
    const x = sx(i);
    if (f < 0) {
      s += `<path class="cd-mute" d="M${x - 4} 10 l8 8 M${x + 4} 10 l-8 8" fill="none"/>`;
    } else if (f === 0) {
      s += `<circle class="cd-open" cx="${x}" cy="14" r="4"/>`;
    } else {
      const rel = f - base + 1;
      const y = fy(rel) - h / rows / 2;
      s += `<circle class="cd-dot" cx="${x}" cy="${y}" r="7"/>`;
      if (fingerOf[i]) {
        s += `<text class="cd-dot-num" x="${x}" y="${y + 3}"
                text-anchor="middle">${fingerOf[i]}</text>`;
      }
    }
  });
  return `<svg viewBox="0 0 118 116" role="img">${s}</svg>`;
}

/* Chord ribbon: the song as a strip of chord blocks, synced to the stem player.
   Replaces the old wall-of-timestamps chart. */
function renderChordRibbon(chords) {
  const wrap = $("ribbon-wrap");
  const ribbon = $("chord-ribbon");
  ribbon.innerHTML = "";
  const spans = chords.filter((c) => c.end > c.start);
  if (!spans.length) { wrap.hidden = true; return; }
  wrap.hidden = false;
  const audio = $("stem-audio");
  const PX_PER_SECOND = 14;   // fixed scale so long songs scroll instead of squish
  for (const c of spans) {
    const block = document.createElement("button");
    block.type = "button";
    block.className = "rseg" + (c.chord === "N" ? " rest" : "");
    // never truncate a chord name: width fits the label, then scales with time
    const label = c.chord === "N" ? "" : c.chord;
    const labelPx = 18 + label.length * 9;
    const px = Math.max((c.end - c.start) * PX_PER_SECOND,
                        c.chord === "N" ? 8 : labelPx);
    block.style.width = `${Math.round(px)}px`;
    block.textContent = c.chord === "N" ? "" : c.chord;
    block.title = `${c.chord === "N" ? "no chord" : c.chord} · ` +
      `${fmtTime(c.start)} to ${fmtTime(c.end)}`;
    block.dataset.start = c.start;
    block.dataset.end = c.end;
    block.addEventListener("click", () => {
      if (audio.src) { audio.currentTime = c.start; audio.play(); }
    });
    ribbon.appendChild(block);
  }
}

// follow playback: light up the chord under the playhead and keep it in view
let lastPlayingBlock = null;
$("stem-audio").addEventListener("timeupdate", (ev) => {
  const t = ev.target.currentTime;
  let playing = null;
  for (const b of document.querySelectorAll(".chord-ribbon .rseg")) {
    const on = t >= +b.dataset.start && t < +b.dataset.end;
    b.classList.toggle("playing", on);
    if (on) playing = b;
  }
  if (playing && playing !== lastPlayingBlock) {
    lastPlayingBlock = playing;
    const ribbon = $("chord-ribbon");
    const target = playing.offsetLeft - ribbon.clientWidth / 2 +
                   playing.offsetWidth / 2;
    ribbon.scrollTo({ left: Math.max(0, target), behavior: "smooth" });
  }
});

function renderChordDiagrams(container, topChords, totalDur) {
  container.innerHTML = "";
  for (const [name, dur] of topChords) {
    const shape = chordShape(name);
    const card = document.createElement("div");
    card.className = "chord-card";
    const share = Math.round((dur / totalDur) * 100);
    card.innerHTML = (shape ? chordSVG(shape) : "") +
      `<div class="chord-name">${esc(name)}</div>` +
      `<div class="chord-share">${share}% of the song</div>`;
    container.appendChild(card);
  }
}

/* ---------- tone scope (whole song vs timeline section) ---------- */

const SEG_COLORS = {
  "clean": "#e6cf9c", "edge-of-breakup": "#e8b25c", "overdrive": "#e8a13c",
  "distortion": "#d47f27", "fuzz/high-gain": "#bf5c1d",
};

function fmtTime(s) {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

function renderTimeline(report) {
  const timeline = (report.tone || {}).timeline || [];
  const bar = $("timeline");
  const ruler = $("timeline-ruler");
  const label = $("timeline-label");
  bar.innerHTML = "";
  ruler.innerHTML = "";
  if (!timeline.length) {
    label.textContent = "No tone timeline in this analysis. Re-analyze the song " +
      "to map how the tone changes over time.";
    return;
  }
  label.textContent = timeline.length === 1
    ? "One consistent tone across the analyzed span"
    : "Tone over the song (click a section to zoom the rig and match target)";
  const total = timeline[timeline.length - 1].end || 1;
  timeline.forEach((seg, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tseg" + (state.segment === i ? " selected" : "");
    btn.style.flexGrow = String(Math.max(seg.end - seg.start, 1));
    btn.style.background = SEG_COLORS[seg.label] || "#e8a13c";
    btn.title = `${fmtTime(seg.start)} to ${fmtTime(seg.end)}: ${seg.label}`;
    btn.textContent = seg.label;
    if (timeline.length > 1) {
      btn.addEventListener("click", () => {
        state.segment = state.segment === i ? -1 : i;
        renderTimeline(report);
        renderToneScope();
      });
    }
    bar.appendChild(btn);
  });
  for (const frac of [0, 0.25, 0.5, 0.75, 1]) {
    const tick = document.createElement("span");
    tick.textContent = fmtTime(total * frac);
    ruler.appendChild(tick);
  }
}

function currentScope() {
  const tone = (state.report && state.report.tone) || {};
  const timeline = tone.timeline || [];
  if (state.segment >= 0 && state.segment < timeline.length) {
    const seg = timeline[state.segment];
    return {
      est: seg.estimate,
      model: seg.model_params || null,
      feats: seg.features || null,
      label: `section ${state.segment + 1} (${fmtTime(seg.start)} to ` +
             `${fmtTime(seg.end)}, ${seg.label})`,
    };
  }
  return {
    est: tone.estimate || null,
    model: (tone.model_estimate || {}).params || null,
    feats: tone.features || null,
    label: "whole song",
  };
}

/* ---------- knobs ---------- */

function knobHTML(label, norm, display, extraClass) {
  const angle = -135 + 270 * Math.max(0, Math.min(1, norm));
  let ticks = "";
  for (let i = 0; i <= 10; i++) {
    const a = (-135 + 27 * i) * Math.PI / 180;
    const x1 = 40 + 30 * Math.sin(a), y1 = 40 - 30 * Math.cos(a);
    const x2 = 40 + 34 * Math.sin(a), y2 = 40 - 34 * Math.cos(a);
    ticks += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}"
      x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"/>`;
  }
  return `<div class="knob-unit ${extraClass || ""}">
    <svg viewBox="0 0 80 80" aria-label="${esc(label)}: ${esc(display)}">
      <g class="knob-ticks">${ticks}</g>
      <circle class="knob-face" cx="40" cy="40" r="26"/>
      <g class="knob-needle" style="transform: rotate(${angle.toFixed(1)}deg)">
        <line x1="40" y1="40" x2="40" y2="18"/>
      </g>
      <circle class="knob-cap" cx="40" cy="40" r="4"/>
    </svg>
    <div class="knob-val">${esc(display)}</div>
    <div class="knob-name">${esc(label)}</div>
  </div>`;
}

function mv(model, name) {
  const p = model && model[name];
  return (p && typeof p === "object" && p.value != null) ? p.value : null;
}

function knobsForEffect(fx, feats, model) {
  const f = feats || {};
  const effect = fx.effect;
  const knobs = [];
  if (["clean", "edge-of-breakup", "overdrive", "distortion",
       "fuzz/high-gain"].includes(effect)) {
    const db = mv(model, "drive_db");
    knobs.push(db != null
      ? { label: "drive", norm: db / 35, display: `${db.toFixed(0)} dB` }
      : { label: "drive", norm: fx.strength, display: `${Math.round(fx.strength * 100)}%` });
  } else if (effect === "compressor") {
    const ratio = mv(model, "comp_ratio");
    if (ratio != null && ratio > 1.2) {
      knobs.push({ label: "ratio", norm: (ratio - 1) / 7,
                   display: `${ratio.toFixed(1)}:1` });
    } else {
      knobs.push({ label: "squash", norm: fx.strength,
                   display: `${Math.round(fx.strength * 100)}%` });
    }
  } else if (effect === "chorus") {
    const rate = mv(model, "chorus_rate_hz"), mix = mv(model, "chorus_mix");
    if (rate != null) knobs.push({ label: "rate", norm: rate / 4,
                                   display: `${rate.toFixed(1)} Hz` });
    if (mix != null) knobs.push({ label: "mix", norm: mix / 0.6,
                                  display: `${Math.round(mix * 100)}%` });
  } else if (effect === "modulation") {
    knobs.push({ label: "rate", norm: (f.modulation_hz || 0) / 12,
                 display: `${(f.modulation_hz || 0).toFixed(1)} Hz` });
    knobs.push({ label: "depth", norm: Math.min((f.modulation_depth || 0) * 2, 1),
                 display: `${Math.round(Math.min((f.modulation_depth || 0) * 2, 1) * 100)}%` });
  } else if (effect === "delay") {
    const t = mv(model, "delay_seconds") ?? f.echo_delay_s ?? 0;
    const mix = mv(model, "delay_mix") ?? Math.min(f.echo_strength || 0, 0.5);
    knobs.push({ label: "time", norm: t / 0.8, display: `${Math.round(t * 1000)} ms` });
    knobs.push({ label: "mix", norm: mix / 0.5, display: `${Math.round(mix * 100)}%` });
  } else if (effect.startsWith("reverb")) {
    knobs.push({ label: "decay", norm: (f.decay_t60_s || 0) / 6,
                 display: `${(f.decay_t60_s || 0).toFixed(1)} s` });
    const wet = mv(model, "reverb_wet");
    if (wet != null) knobs.push({ label: "wet", norm: wet / 0.6,
                                  display: `${Math.round(wet * 100)}%` });
  }
  return knobs;
}

function renderToneScope() {
  const report = state.report;
  if (!report) return;
  const { est, model, feats, label } = currentScope();

  const scopeNote = $("scope-note");
  if (state.segment >= 0) {
    scopeNote.innerHTML = `Showing ${esc(label)}. `;
    const back = document.createElement("button");
    back.type = "button";
    back.textContent = "Show whole song";
    back.addEventListener("click", () => {
      state.segment = -1;
      renderTimeline(report);
      renderToneScope();
    });
    scopeNote.appendChild(back);
  } else {
    scopeNote.textContent = "";
  }
  $("match-scope").textContent = label;
  $("tone-summary").textContent = est
    ? est.summary : "Tone analysis unavailable.";

  // stompbox colors, muted: dirt = warm hues, time/space = cool hues
  const PEDAL_HUES = {
    "clean": 45, "edge-of-breakup": 80, "overdrive": 100, "distortion": 20,
    "fuzz/high-gain": 0, "compressor": 205, "chorus": 175, "modulation": 320,
    "delay": 235, "reverb": 280, "reverb (uncertain)": 280,
  };
  const board = $("pedalboard");
  board.innerHTML = "";
  if (est) {
    for (const fx of est.chain) {
      const div = document.createElement("div");
      div.className = "pedal" + (fx.effect.includes("uncertain") ? " uncertain" : "");
      div.style.setProperty("--ph", PEDAL_HUES[fx.effect] ?? 35);
      const dials = knobsForEffect(fx, feats, model)
        .map((k) => knobHTML(k.label, k.norm, k.display)).join("");
      const settings = Object.entries(fx.settings).map(([k, v]) =>
        `<div class="knob"><b>${esc(k)}</b><span>${esc(v)}</span></div>`).join("");
      div.innerHTML = `
        <span class="led"></span>
        <h3>${esc(fx.effect)}</h3>
        <div class="verdict">${esc(fx.verdict)}</div>
        <div class="dials">${dials}</div>
        <div class="knobs">${settings}</div>
        <details class="why-details">
          <summary>why this guess?</summary>
          <div class="why-pop">${esc(fx.evidence)}</div>
        </details>`;
      board.appendChild(div);
    }
  }

  const amp = $("amp-eq");
  amp.innerHTML = "";
  if (est && est.amp_eq && Object.keys(est.amp_eq).length) {
    const order = ["bass", "mids", "treble"];
    const dials = order.filter((k) => est.amp_eq[k]).map((k) => {
      const v = est.amp_eq[k];
      const nums = String(v).match(/\d+/g) || ["5"];
      const mid = nums.map(Number).reduce((a, b) => a + b, 0) / nums.length;
      return knobHTML(k, mid / 10, String(v).replace(/\s*\(.*\)/, ""));
    }).join("");
    amp.innerHTML = `<span class="amp-label">Amp EQ<br>starting point</span>
      <div class="amp-dials">${dials}</div>`;
  }

  renderModelStrip(model);
}

function renderModelStrip(params) {
  const strip = $("modelstrip");
  if (!params) { strip.hidden = true; return; }
  const fmt = (p, f) => p && p.value != null
    ? f(p.value) + (p.mae != null ? ` ±${f(p.mae, true)}` : "") : null;
  const pieces = [
    ["drive", fmt(params.drive_db, (v) => `${v.toFixed(1)} dB`)],
    ["reverb wet", fmt(params.reverb_wet, (v) => `${Math.round(v * 100)}%`)],
    ["room size", fmt(params.reverb_room, (v) => v.toFixed(2))],
    ["delay", fmt(params.delay_seconds, (v) => `${Math.round(v * 1000)} ms`)],
    ["delay mix", fmt(params.delay_mix, (v) => `${Math.round(v * 100)}%`)],
    ["chorus rate", fmt(params.chorus_rate_hz, (v) => `${v.toFixed(1)} Hz`)],
    ["chorus mix", fmt(params.chorus_mix, (v) => `${Math.round(v * 100)}%`)],
    ["compression", params.comp_ratio && params.comp_ratio.value > 1.2
      ? `${params.comp_ratio.value.toFixed(1)}:1` : null],
  ].filter(([, v]) => v);
  $("modelstrip-values").innerHTML = pieces.map(([k, v]) =>
    `${esc(k)} <span class="mval">${esc(v)}</span>`).join(" &nbsp; ");
  strip.hidden = pieces.length === 0;
}

/* ---------- tone match (record / upload an attempt) ---------- */

async function submitMatch(blob, filename) {
  const errEl = $("match-error");
  errEl.hidden = true;
  $("advice-list").innerHTML =
    '<li class="close"><span class="a-aspect">...</span>' +
    '<span class="a-text">analyzing your recording</span></li>';
  try {
    const form = new FormData();
    form.append("audio", blob, filename);
    form.append("segment", String(state.segment));
    const res = await fetch(`/api/jobs/${state.reportJobId}/match`,
                            { method: "POST", body: form });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (e) { /* keep */ }
      throw new Error(detail);
    }
    const payload = await res.json();
    const ul = $("advice-list");
    ul.innerHTML = "";
    // per-aspect scale for the bipolar delta bar (full bar = this much delta)
    const SCALES = { drive: 1, brightness: 6, mids: 0.3, reverb: 3,
                     delay: 0.5, chorus: 0.5, dynamics: 10 };
    for (const a of payload.advice) {
      const li = document.createElement("li");
      li.className = a.status;
      const scale = SCALES[a.aspect] || 1;
      const pct = Math.min(Math.abs(a.delta) / scale, 1) * 50;
      const side = a.delta >= 0 ? "pos" : "neg";
      li.innerHTML = `<span class="a-aspect">${esc(a.aspect)}</span>
        <span class="a-bar"><i class="${side}" style="width:${pct.toFixed(0)}%"></i></span>
        <span class="a-text">${esc(a.text)}</span>`;
      ul.appendChild(li);
    }
    const cav = $("match-caveat");
    cav.textContent = payload.caveat;
    cav.hidden = false;
  } catch (e) {
    $("advice-list").innerHTML = "";
    errEl.textContent = e.message;
    errEl.hidden = false;
  }
}

$("match-file").addEventListener("change", (ev) => {
  const file = ev.target.files[0];
  if (file) submitMatch(file, file.name);
  ev.target.value = "";
});
document.querySelector(".upload-label").addEventListener("click", (ev) => {
  ev.preventDefault();
  $("match-file").click();
});

$("record-btn").addEventListener("click", async () => {
  const btn = $("record-btn");
  if (state.recorder && state.recorder.state === "recording") {
    state.recorder.stop();
    return;
  }
  const errEl = $("match-error");
  errEl.hidden = true;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false,
               autoGainControl: false },
    });
  } catch (e) {
    errEl.textContent = "Microphone access denied: " + e.message;
    errEl.hidden = false;
    return;
  }
  const chunks = [];
  const rec = new MediaRecorder(stream);
  state.recorder = rec;
  rec.ondataavailable = (ev) => { if (ev.data.size) chunks.push(ev.data); };
  rec.onstop = () => {
    clearInterval(state.recTimer);
    $("rec-timer").hidden = true;
    btn.textContent = "Record";
    btn.classList.remove("recording");
    stream.getTracks().forEach((t) => t.stop());
    const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
    if (blob.size > 2000) submitMatch(blob, "attempt.webm");
  };
  rec.start();
  btn.textContent = "Stop";
  btn.classList.add("recording");
  const started = Date.now();
  const timerEl = $("rec-timer");
  timerEl.hidden = false;
  state.recTimer = setInterval(() => {
    timerEl.textContent = fmtTime((Date.now() - started) / 1000);
  }, 250);
});

function renderError(job) {
  $("error-title").textContent = job.title || job.source;
  $("error-body").textContent = job.error || "Analysis failed.";
  show("error-view");
}

/* ---------- polling / render loop ---------- */

async function refreshJobs() {
  try {
    state.jobs = await api("/api/jobs");
  } catch (e) { /* server briefly away; keep last state */ }
  render();
}

async function render() {
  renderJobs();
  const job = state.jobs.find((j) => j.id === state.selected);
  if (!job) { show("stage-empty"); state.renderedKey = null; return; }

  if (job.status === "queued" || job.status === "running") {
    state.renderedKey = null;
    renderProgress(job);
  } else if (job.status === "done") {
    // A finished report is static: re-rendering it on every poll tick would
    // reset the stem player and lose scroll/details state. Render once.
    const key = `${job.id}:${job.status}`;
    if (state.renderedKey === key) return;
    try {
      const report = await api(`/api/jobs/${job.id}/report`);
      renderReport(job, report);
      state.renderedKey = key;
      const wasRunning = state.reportJobId === job.id;
      if (!wasRunning) $("stage").scrollTop = 0;
    } catch (e) {
      renderError({ ...job, error: "report missing: " + e.message });
    }
  } else {
    state.renderedKey = null;
    renderError(job);
  }
}

function startPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    state.pollTick += 1;
    const active = state.jobs.some((j) => j.status === "queued" || j.status === "running");
    // fast poll while something runs; slow heartbeat otherwise so the library
    // stays fresh (other tabs, deleted jobs) without hammering the server
    if (active || state.pollTick % 5 === 0) await refreshJobs();
  }, 1600);
}

/* ---------- section tabs ---------- */

const tabsNav = $("section-tabs");
tabsNav.addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-target]");
  if (!btn) return;
  const el = $(btn.dataset.target);
  if (!el) return;
  // scroll the stage pane directly: deterministic in a nested scroll container
  const stage = $("stage");
  const top = el.getBoundingClientRect().top - stage.getBoundingClientRect().top
              + stage.scrollTop - 12;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  stage.scrollTo({ top: Math.max(0, top), behavior: reduce ? "auto" : "smooth" });
  // reflect the choice immediately instead of waiting for the scroll-spy
  for (const b of tabsNav.querySelectorAll("button")) {
    b.classList.toggle("active", b === btn);
  }
});

// scroll-spy: highlight the tab of the section nearest the top of the stage
const spy = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    for (const b of tabsNav.querySelectorAll("button")) {
      b.classList.toggle("active", b.dataset.target === entry.target.id);
    }
  }
}, { root: $("stage"), rootMargin: "-15% 0px -70% 0px" });
for (const id of ["panel-tone", "panel-match", "panel-rig",
                  "panel-transcription", "panel-data"]) {
  const el = $(id);
  if (el) spy.observe(el);
}

refreshHealth();
refreshJobs().then(() => {
  // preselect the most recent job so reopening the dashboard shows something
  if (!state.selected && state.jobs.length) {
    state.selected = state.jobs[0].id;
    render();
  }
});
startPolling();
