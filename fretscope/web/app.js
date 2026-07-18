/* FretScope dashboard. Vanilla JS, polls the job API. */

"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  jobs: [],
  selected: null,
  pollTimer: null,
  report: null,        // report of the currently displayed job
  reportJobId: null,
  segment: -1,         // -1 = whole song, else tone-timeline section index
  recorder: null,
  recTimer: null,
};

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
    const bits = [];
    bits.push(h.ffmpeg ? "ffmpeg ready" : '<span class="warn">ffmpeg missing</span>');
    bits.push(h.separation_available
      ? "separation ready"
      : '<span class="warn">separation off (full mix)</span>');
    $("health").innerHTML = bits.join(" &nbsp;&middot;&nbsp; ");
  } catch (e) {
    $("health").innerHTML = '<span class="warn">server unreachable</span>';
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
    await refreshJobs();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.hidden = false;
  } finally {
    $("submit-btn").disabled = false;
  }
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
    li.querySelector(".jobsub").textContent = statusLabel(job);
    li.addEventListener("click", () => { state.selected = job.id; render(); });
    li.querySelector(".del").addEventListener("click", async (ev) => {
      ev.stopPropagation();
      try {
        await api(`/api/jobs/${job.id}`, { method: "DELETE" });
        if (state.selected === job.id) state.selected = null;
        await refreshJobs();
      } catch (e) { /* active job; ignore */ }
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

  // stem player
  const hasStem = report.separation && report.separation.separated;
  $("player-wrap").hidden = !hasStem;
  if (hasStem) $("stem-audio").src = `/api/jobs/${job.id}/stem`;

  // separation banner
  const sep = report.separation;
  $("separation-banner").textContent = sep
    ? (sep.separated
        ? `Guitar isolated with ${sep.method}. ${sep.notes[0] || ""}`
        : `Heads up: ${sep.notes[0] || "analysis ran on the full mix."}`)
    : "";

  // transcription
  const tr = report.transcription || {};
  const heading = $("transcription-heading");
  const body = $("transcription-body");
  const note = $("classification-note");
  if (tr.kind === "lead") {
    heading.textContent = "Tab";
    body.textContent = tr.tab || "(empty)";
    note.textContent = "Read as a lead line: " + (tr.classification?.rationale || "");
  } else if (tr.kind === "rhythm") {
    heading.textContent = "Chord chart";
    body.textContent = tr.chart || "(empty)";
    note.textContent = "Read as a chordal part: " + (tr.classification?.rationale || "");
  } else {
    heading.textContent = "Transcription";
    body.textContent = "Unavailable: " + (tr.error || "unknown failure");
    note.textContent = "";
  }

  // tone (scoped: whole song or a timeline section)
  if (state.reportJobId !== job.id) state.segment = -1;
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
  const wrap = $("timeline-wrap");
  wrap.hidden = timeline.length < 2;
  const bar = $("timeline");
  bar.innerHTML = "";
  if (timeline.length < 2) return;
  const total = timeline[timeline.length - 1].end || 1;
  timeline.forEach((seg, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tseg" + (state.segment === i ? " selected" : "");
    btn.style.flexGrow = String(Math.max(seg.end - seg.start, 1));
    btn.style.background = SEG_COLORS[seg.label] || "#e8a13c";
    btn.title = `${fmtTime(seg.start)} to ${fmtTime(seg.end)}: ${seg.label}`;
    btn.textContent = seg.label;
    btn.addEventListener("click", () => {
      state.segment = state.segment === i ? -1 : i;
      renderTimeline(report);
      renderToneScope();
    });
    bar.appendChild(btn);
  });
}

function currentScope() {
  const tone = (state.report && state.report.tone) || {};
  const timeline = tone.timeline || [];
  if (state.segment >= 0 && state.segment < timeline.length) {
    const seg = timeline[state.segment];
    return {
      est: seg.estimate,
      model: seg.model_params || null,
      label: `section ${state.segment + 1} (${fmtTime(seg.start)} to ` +
             `${fmtTime(seg.end)}, ${seg.label})`,
    };
  }
  return {
    est: tone.estimate || null,
    model: (tone.model_estimate || {}).params || null,
    label: "whole song",
  };
}

function renderToneScope() {
  const report = state.report;
  if (!report) return;
  const { est, model, label } = currentScope();

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
      div.className = "pedal";
      const knobs = Object.entries(fx.settings).map(([k, v]) =>
        `<div class="knob"><b>${esc(k)}</b><span>${esc(v)}</span></div>`).join("");
      div.innerHTML = `
        <h3>${esc(fx.effect)}</h3>
        <div class="verdict">${esc(fx.verdict)}</div>
        <div class="strength"><i style="width:${Math.round(fx.strength * 100)}%"></i></div>
        <div class="knobs">${knobs}</div>
        <div class="evidence">${esc(fx.evidence)}</div>`;
      board.appendChild(div);
    }
  }

  const amp = $("amp-eq");
  amp.innerHTML = "";
  if (est && est.amp_eq && Object.keys(est.amp_eq).length) {
    amp.innerHTML = '<span class="amp-label">Amp EQ starting point</span>' +
      Object.entries(est.amp_eq).map(([k, v]) =>
        `<div class="ampknob"><div class="val">${esc(v)}</div>
         <div class="name">${esc(k)}</div></div>`).join("");
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
    for (const a of payload.advice) {
      const li = document.createElement("li");
      li.className = a.status;
      li.innerHTML = `<span class="a-aspect">${esc(a.aspect)}</span>
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
  if (!job) { show("stage-empty"); return; }

  if (job.status === "queued" || job.status === "running") {
    renderProgress(job);
  } else if (job.status === "done") {
    try {
      const report = await api(`/api/jobs/${job.id}/report`);
      renderReport(job, report);
    } catch (e) {
      renderError({ ...job, error: "report missing: " + e.message });
    }
  } else {
    renderError(job);
  }
}

function startPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    const active = state.jobs.some((j) => j.status === "queued" || j.status === "running");
    if (active) await refreshJobs();
  }, 1500);
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
