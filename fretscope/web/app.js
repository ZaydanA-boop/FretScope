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
  try {
    const h = await api("/api/health");
    const chip = (ok, on, off) =>
      `<span class="chip ${ok ? "" : "off"}">${ok ? on : off}</span>`;
    $("health").innerHTML =
      chip(h.ffmpeg, "audio engine", "ffmpeg missing") +
      chip(h.separation_available, "separation", "separation off") +
      chip(h.model_available, "tone model", "no tone model");
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

  // transcription: tab shown in full; chord charts are bulky so they collapse
  const tr = report.transcription || {};
  const heading = $("transcription-heading");
  const body = $("transcription-body");
  const note = $("classification-note");
  const chordsDetails = $("chords-details");
  chordsDetails.hidden = true;
  chordsDetails.open = false;
  body.hidden = false;
  if (tr.kind === "lead") {
    heading.textContent = "Tab";
    body.textContent = tr.tab || "(empty)";
    note.textContent = "Read as a lead line: " + (tr.classification?.rationale || "");
  } else if (tr.kind === "rhythm") {
    heading.textContent = "Rhythm part";
    body.hidden = true;
    note.textContent = "Read as a chordal part: " +
      (tr.classification?.rationale || "");
    const chords = (tr.chords || []).filter((c) => c.chord !== "N");
    if (chords.length) {
      const dur = {};
      for (const c of chords) dur[c.chord] = (dur[c.chord] || 0) + (c.end - c.start);
      const top = Object.entries(dur).sort((a, b) => b[1] - a[1]).slice(0, 4)
        .map(([name]) => name);
      note.textContent += ` Mostly ${top.join(", ")}.`;
    }
    $("chords-body").textContent = tr.chart || "(empty)";
    chordsDetails.hidden = false;
  } else {
    heading.textContent = "Transcription";
    body.textContent = "Unavailable: " + (tr.error || "unknown failure");
    note.textContent = "";
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

  // measurements
  const f = (report.tone || {}).features || {};
  const dl = $("measurements");
  dl.innerHTML = "";
  const rows = [
    ["level", f.rms_db != null ? f.rms_db + " dB RMS" : null],
    ["crest factor", f.crest_db != null ? f.crest_db + " dB" : null],
    ["clipping ratio", f.flat_top_ratio],
    ["harmonic index", f.harmonic_distortion],
    ["brightness", f.spectral_centroid_hz != null ? f.spectral_centroid_hz + " Hz" : null],
    ["spectral tilt", f.tilt_db_per_octave != null ? f.tilt_db_per_octave + " dB/oct" : null],
    ["decay (T60 est.)", f.decay_t60_s != null ? f.decay_t60_s + " s" : null],
    ["dynamic range", f.dynamic_range_db != null ? f.dynamic_range_db + " dB" : null],
  ];
  for (const [k, v] of rows) {
    if (v == null) continue;
    const div = document.createElement("div");
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
    knobs.push({ label: "squash", norm: fx.strength,
                 display: `${Math.round(fx.strength * 100)}%` });
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

  const board = $("pedalboard");
  board.innerHTML = "";
  if (est) {
    for (const fx of est.chain) {
      const div = document.createElement("div");
      div.className = "pedal" + (fx.effect.includes("uncertain") ? " uncertain" : "");
      const dials = knobsForEffect(fx, feats, model)
        .map((k) => knobHTML(k.label, k.norm, k.display)).join("");
      const settings = Object.entries(fx.settings).map(([k, v]) =>
        `<div class="knob"><b>${esc(k)}</b><span>${esc(v)}</span></div>`).join("");
      div.innerHTML = `
        <h3>${esc(fx.effect)}</h3>
        <div class="verdict">${esc(fx.verdict)}</div>
        <div class="dials">${dials}</div>
        <div class="knobs">${settings}</div>
        <div class="evidence">${esc(fx.evidence)}</div>`;
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
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
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
