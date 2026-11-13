// Clipzer v2 front end. Built, developed & owned by K S Pankaj.
const $ = (id) => document.getElementById(id);
const STAGES = ["import", "transcribe", "analyze", "moments", "render", "write"];
const DEFAULTS = {
  num: 6, min: 25, max: 50, aspect: "9:16", style: "bold", title: true, lang: "", framing: "face",
  genre: "auto", focus: "", tone: "curious", norm: true, silence: false, mark: "", credit: "",
};
const ASPECTS = ["9:16", "1:1", "4:5", "16:9"];
const FRAMINGS = { face: "Face", center: "Centre", blur: "Blur fill" };
const EDIT_FRAMINGS = { face: "Face", center: "Centre", blur: "Blur", manual: "Manual" };
const PLATFORMS = { youtube: "YouTube", instagram: "Reels", x: "X", linkedin: "LinkedIn" };

let meta = null;
let settings = load("clipzer-settings", DEFAULTS);
let source = { kind: "link", file: null, check: null };
let project = null;        // the open project (full job object)
let pollTimer = null;
let editing = null;        // clip id open in the editor
let draft = null;          // the editor's unsaved values
let transcript = null;     // transcript of the open project, for the editor
let platform = "youtube";

/* ---------------------------------------------------------------- utilities */
function load(key, fallback) {
  try { return { ...fallback, ...(JSON.parse(localStorage.getItem(key)) || {}) }; } catch { return { ...fallback }; }
}
function store(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } }
async function api(path, options = {}) {
  if (options.json !== undefined) {
    options.body = JSON.stringify(options.json);
    options.headers = { "Content-Type": "application/json" };
    delete options.json;
  }
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data;
}
function clock(s) {
  s = Math.max(0, s || 0);
  const m = Math.floor(s / 60), r = s - m * 60;
  return `${String(m).padStart(2, "0")}:${r.toFixed(1).padStart(4, "0")}`;
}
function shortClock(s) {
  s = Math.round(s || 0);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
}
function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) node.append(kid.nodeType ? kid : document.createTextNode(kid));
  return node;
}
let toastTimer;
function toast(text) {
  const t = $("toast");
  t.textContent = text; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 2200);
}
function fillRange(input) {
  const pct = ((input.value - input.min) / (input.max - input.min)) * 100;
  input.style.setProperty("--fill", `${pct}%`);
}
function segmented(container, options, value, onPick) {
  container.innerHTML = "";
  for (const [key, label] of Object.entries(options)) {
    const b = el("button", { type: "button", role: "radio", "aria-checked": String(key === value) }, label);
    b.addEventListener("click", () => {
      container.querySelectorAll("button").forEach((x) => x.setAttribute("aria-checked", "false"));
      b.setAttribute("aria-checked", "true");
      onPick(key);
    });
    container.append(b);
  }
}
function styleTiles(container, value, onPick) {
  container.innerHTML = "";
  for (const [key, p] of Object.entries(meta.presets)) {
    const sample = el("span", { style: `font-family:"${p.font}";color:${p.active}` }, p.upper ? "WOW" : "Wow");
    const tile = el("button", { type: "button", class: "style-tile", role: "radio", "aria-checked": String(key === value), title: p.label }, sample, el("small", {}, p.label.split(" ")[0]));
    tile.addEventListener("click", () => {
      container.querySelectorAll(".style-tile").forEach((x) => x.setAttribute("aria-checked", "false"));
      tile.setAttribute("aria-checked", "true");
      onPick(key);
    });
    container.append(tile);
  }
}
const media = (job, file) => `/media/${job.id}/${encodeURIComponent(file)}`;

/* ---------------------------------------------------------------- loader + globe */
const minimumWait = new Promise((done) => setTimeout(done, 1700));
const loaderGlobe = new Globe($("loader-globe"), { interactive: false, speed: 40, step: 2.2 });
let heroGlobe = null;
document.fonts.ready.then(() => { heroGlobe = new Globe($("hero-globe")); });

/* ---------------------------------------------------------------- health + controls */
async function loadMeta() {
  meta = await api("/api/health");
  const chips = [
    [meta.whisper, meta.whisper ? `Whisper ${meta.whisper_model}` : "Whisper not installed"],
    [meta.encoder === "h264_nvenc", meta.encoder === "h264_nvenc" ? "GPU encode" : "CPU encode"],
    [meta.ai !== "none", meta.ai !== "none" ? meta.ai_label : "AI: built-in scorer"],
    [meta.ytdlp, meta.ytdlp ? "Links on" : "yt-dlp missing"],
  ];
  $("chips").innerHTML = "";
  chips.forEach(([ok, label]) => $("chips").append(el("li", { class: ok ? "on" : "off" }, label)));
}

function paintControls() {
  const s = settings;
  const ranges = [["c-num", "num", "o-num", (v) => v], ["c-min", "min", "o-min", (v) => `${v}s`], ["c-max", "max", "o-max", (v) => `${v}s`]];
  for (const [id, key, out, fmt] of ranges) {
    const input = $(id);
    input.value = s[key]; $(out).textContent = fmt(s[key]); fillRange(input);
    input.oninput = () => {
      s[key] = Number(input.value);
      if (key === "min" && s.min >= s.max) { s.max = Math.min(120, s.min + 5); }
      if (key === "max" && s.max <= s.min) { s.min = Math.max(10, s.max - 5); }
      store("clipzer-settings", s);
      paintControls();
    };
  }
  segmented($("c-aspect"), Object.fromEntries(ASPECTS.map((a) => [a, a])), s.aspect, (v) => { s.aspect = v; store("clipzer-settings", s); });
  segmented($("c-framing"), FRAMINGS, s.framing, (v) => { s.framing = v; store("clipzer-settings", s); });
  styleTiles($("c-style"), s.style, (v) => { s.style = v; store("clipzer-settings", s); });
  $("c-genre").innerHTML = "";
  for (const [k, label] of Object.entries(meta.genres)) $("c-genre").add(new Option(label, k));
  $("c-tone").innerHTML = "";
  for (const t of meta.tones) $("c-tone").add(new Option(t[0].toUpperCase() + t.slice(1), t));
  const bind = [["c-title", "title", "checked"], ["c-norm", "norm", "checked"], ["c-silence", "silence", "checked"],
    ["c-lang", "lang", "value"], ["c-genre", "genre", "value"], ["c-tone", "tone", "value"],
    ["c-focus", "focus", "value"], ["c-mark", "mark", "value"], ["c-credit", "credit", "value"]];
  for (const [id, key, prop] of bind) {
    $(id)[prop] = s[key];
    $(id).onchange = $(id).oninput = () => { s[key] = $(id)[prop]; store("clipzer-settings", s); };
  }
}
$("reset-controls").onclick = () => { settings = { ...DEFAULTS }; store("clipzer-settings", settings); paintControls(); toast("Controls reset"); };

/* ---------------------------------------------------------------- source: link or file */
function setError(text) { $("form-error").textContent = text || ""; $("form-error").hidden = !text; }
function showSource(node) { $("source-text").innerHTML = ""; $("source-text").append(node); }
function resetSource() {
  source = { kind: "link", file: null, check: null };
  showSource(el("span", {}, "or ", el("button", { type: "button", class: "link", onclick: () => $("file").click() }, "choose a file")));
}
$("attach").onclick = () => $("file").click();
$("attach-2").onclick = () => $("file").click();
$("file").addEventListener("change", () => { if ($("file").files[0]) pickFile($("file").files[0]); });
function pickFile(file) {
  source = { kind: "file", file, check: null };
  $("url").value = "";
  showSource(el("span", {}, el("strong", {}, file.name), ` · ${(file.size / 1048576).toFixed(0)} MB`));
}
let checkTimer;
$("url").addEventListener("input", () => {
  source = { kind: "link", file: null, check: null };
  clearTimeout(checkTimer);
  const url = $("url").value.trim();
  if (!/^https?:\/\/\S+\.\S+/.test(url)) { resetSource(); return; }
  showSource(el("span", {}, "Reading the link…"));
  checkTimer = setTimeout(() => checkLink(url), 450);
});
async function checkLink(url) {
  try {
    const info = await api("/api/check", { method: "POST", json: { url } });
    if ($("url").value.trim() !== url) return;
    source.check = info;
    if (info.ok) showSource(el("span", {}, el("strong", {}, info.title), info.channel ? ` · ${info.channel}` : "", info.duration ? ` · ${shortClock(info.duration)}` : ""));
    else showSource(el("span", { class: "bad" }, info.reason));
  } catch (error) {
    showSource(el("span", { class: "bad" }, error.message));
  }
}
const canvas = $("canvas");
["dragenter", "dragover"].forEach((e) => canvas.addEventListener(e, (ev) => { ev.preventDefault(); $("pill").classList.add("over"); }));
["dragleave", "drop"].forEach((e) => canvas.addEventListener(e, (ev) => { ev.preventDefault(); $("pill").classList.remove("over"); }));
canvas.addEventListener("drop", (ev) => { const f = ev.dataTransfer.files[0]; if (f) pickFile(f); });

/* ---------------------------------------------------------------- start a project */
$("composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("");
  const url = $("url").value.trim();
  if (source.kind === "file" && !source.file) return setError("Choose a video file first.");
  if (source.kind === "link" && !url) return setError("Paste a video link or choose a file.");
  if (source.kind === "link" && source.check && !source.check.ok) return setError(source.check.reason);
  if (!$("rights").checked) return setError("Tick the box to confirm you're allowed to clip this video.");
  const s = settings;
  const body = new FormData();
  const fields = {
    rights: true, num_clips: s.num, min_len: s.min, max_len: s.max, style: s.style, framing: s.framing, aspect: s.aspect,
    language: s.lang, show_title: s.title, genre: s.genre, focus: s.focus, remove_silence: s.silence, normalize: s.norm,
    tone: s.tone, watermark: s.mark, credit: s.credit,
  };
  for (const [k, v] of Object.entries(fields)) body.append(k, String(v));
  if (source.kind === "file") body.append("file", source.file); else body.append("url", url);
  const send = $("send");
  send.disabled = true;
  try {
    const job = await api("/api/jobs", { method: "POST", body });
    $("url").value = ""; resetSource(); $("file").value = "";
    openProject(job.id);
    loadLibrary();
  } catch (error) {
    setError(error.message);
  } finally {
    send.disabled = false;
  }
});

/* ---------------------------------------------------------------- open project + polling */
function busy(job) {
  return ["queued", "running"].includes(job.status) || job.clips.some((c) => ["queued", "rendering"].includes(c.render?.status) || c.publish_busy);
}
async function openProject(id, scroll = true) {
  clearTimeout(pollTimer);
  transcript = null;
  try { project = await api(`/api/jobs/${id}`); } catch (error) { toast(error.message); return; }
  paintProject();
  if (scroll) $("stage").scrollIntoView({ behavior: "smooth" });
  poll();
}
async function poll() {
  clearTimeout(pollTimer);
  if (!project) return;
  try {
    const fresh = await api(`/api/jobs/${project.id}`);
    const wasBusy = busy(project);
    project = fresh;
    paintProject();
    if (editing) paintEditorStatus();
    if (wasBusy && !busy(project)) loadLibrary();
  } catch { /* server busy; try again */ }
  if (project && busy(project)) pollTimer = setTimeout(poll, 1200);
}
function closeProject() {
  project = null;
  clearTimeout(pollTimer);
  paintProject();
}

function paintProject() {
  const job = project;
  const running = job && ["queued", "running"].includes(job.status);
  const failed = job && ["failed", "cancelled"].includes(job.status);
  $("composer").hidden = !!(job && (running || failed || job.clips.length));
  $("run").hidden = !(running || failed);
  $("reel").hidden = !(job && job.clips.length);
  if (!job) {
    $("mega-a").textContent = "TRY IT"; $("mega-b").textContent = "YOUR WAY";
    $("mega-sub").textContent = "Paste a link or drop a file. Clipzer finds the hooks, cuts them to 9:16 and captions every word.";
    return;
  }
  const stage = job.status === "done" ? STAGES.length : Math.max(0, STAGES.indexOf(job.stage));
  const words = { import: ["BRING", "IT IN"], transcribe: ["LISTEN", "CLOSELY"], analyze: ["FEEL", "THE ROOM"], moments: ["FIND", "THE HOOK"], render: ["CUT", "IT CLEAN"], write: ["SAY", "IT RIGHT"] };
  if (running) {
    const [a, b] = words[job.stage] || ["HOLD", "ON"];
    $("mega-a").textContent = a; $("mega-b").textContent = b;
    $("mega-sub").textContent = job.message || "Working";
  } else if (failed) {
    $("mega-a").textContent = job.status === "cancelled" ? "STOPPED" : "HMM.";
    $("mega-b").textContent = "TRY AGAIN";
    $("mega-sub").textContent = job.status === "cancelled" ? "This project was cancelled." : "Something went wrong. The reason is above.";
  } else {
    $("mega-a").textContent = `${job.clips.length} CLIPS`; $("mega-b").textContent = "READY.";
    $("mega-sub").textContent = "Open a clip to trim it, fix captions, change the look, or grab its titles and hashtags.";
  }
  const overall = job.status === "done" ? 100 : Math.round(((stage + (job.progress || 0) / 100) / STAGES.length) * 100);
  $("run-name").textContent = job.name || "Your video";
  $("run-pct").textContent = `${String(Math.min(overall, 99)).padStart(2, "0")}%`;
  $("run").classList.toggle("failed", failed);
  $("run-msg").textContent = failed ? (job.error || "Cancelled.") : job.message;
  $("cancel").textContent = failed ? "Start a new project" : "Cancel";
  $("cancel").onclick = failed ? () => closeProject() : async () => { try { await api(`/api/jobs/${job.id}/cancel`, { method: "POST" }); } catch (e) { toast(e.message); } };
  document.querySelectorAll("#stages li").forEach((li, i) => { li.className = i < stage ? "done" : i === stage && running ? "now" : ""; });
  paintReel(job, running);
}

function paintReel(job, running) {
  const engine = job.engine === "built-in" ? "the built-in scorer" : job.engine || "the scorer";
  $("reel-note").textContent = running ? job.message : job.note || `Ranked by ${engine}, best first. Click a clip to edit it.`;
  const track = $("track");
  const want = Math.max(job.clips.length, running ? job.options.num_clips : 0);
  while (track.children.length > want) track.lastChild.remove();
  for (let i = 0; i < want; i++) {
    const clip = job.clips[i];
    const key = clip ? `${clip.id}:${clip.version}:${clip.render?.status}` : "pending";
    let tile = track.children[i];
    if (tile && tile.dataset.key === key) continue;
    const frame = el("div", { class: "tile-frame" });
    if (!clip || !clip.file || clip.render?.status !== "ready") frame.append(el("div", { class: "shimmer" }, el("p", {}, clip?.render?.status === "failed" ? "Failed" : "Making")));
    else frame.append(el("img", { src: media(job, clip.thumb) + `?v=${clip.version}`, alt: "", loading: "lazy" }));
    if (clip) frame.append(el("span", { class: "tile-score" }, `${clip.score}`));
    if (clip && ["queued", "rendering"].includes(clip.render?.status) && clip.file) frame.append(el("span", { class: "tile-state" }, "Rendering"));
    const node = el("button", { type: "button", class: "tile", "data-key": key, disabled: !clip },
      frame,
      el("h3", {}, clip ? (clip.edits?.title_text || clip.title) : "Finding a moment…"),
      el("p", {}, clip ? `${clip.duration || (clip.end - clip.start).toFixed(1)}s · ${clip.edits?.aspect || "9:16"}` : " "));
    if (clip) node.addEventListener("click", () => openEditor(clip.id));
    if (tile) tile.replaceWith(node); else track.append(node);
  }
}

/* ---------------------------------------------------------------- library */
async function loadLibrary() {
  let list = [];
  try { list = await api("/api/jobs"); } catch { return; }
  const grid = $("lib-grid");
  grid.innerHTML = "";
  $("lib-count").textContent = list.length ? `${list.length} project${list.length === 1 ? "" : "s"}` : "";
  if (!list.length) { grid.append(el("p", { class: "empty" }, "No projects yet. Your first one will show up here.")); return; }
  for (const j of list) {
    const status = j.status === "done" ? `${j.clips} clips` : j.status === "running" ? `${j.stage} · ${j.progress}%` : j.status;
    const thumb = el("div", { class: "proj-thumb" });
    if (j.thumb) thumb.style.backgroundImage = `url("/media/${j.id}/${encodeURIComponent(j.thumb)}")`;
    const del = el("button", { type: "button", class: "btn small" }, "Delete");
    del.addEventListener("click", async () => {
      if (del.dataset.sure !== "1") { del.dataset.sure = "1"; del.textContent = "Sure?"; setTimeout(() => { del.dataset.sure = ""; del.textContent = "Delete"; }, 3000); return; }
      try { await api(`/api/jobs/${j.id}`, { method: "DELETE" }); if (project?.id === j.id) closeProject(); loadLibrary(); toast("Project deleted"); }
      catch (e) { toast(e.message); }
    });
    grid.append(el("div", { class: "proj" }, thumb, el("div", { style: "min-width:0" },
      el("p", { class: "proj-name", title: j.name }, j.name || j.id),
      el("p", { class: `proj-meta ${j.status}` }, `${status} · ${new Date(j.created * 1000).toLocaleDateString()}`),
      el("div", { class: "proj-actions" }, el("button", { type: "button", class: "btn small", onclick: () => openProject(j.id) }, "Open"), del))));
  }
  if (!project) { const live = list.find((j) => ["queued", "running"].includes(j.status)); if (live) openProject(live.id, false); }
}

/* ---------------------------------------------------------------- editor */
function clipById(id) { return project?.clips.find((c) => c.id === id); }

async function openEditor(id) {
  editing = id;
  const clip = clipById(id);
  if (!clip) return;
  if (!transcript) { try { transcript = await api(`/api/jobs/${project.id}/transcript`); } catch { transcript = { segments: [] }; } }
  draft = { start: clip.start, end: clip.end, edits: { ...clip.edits } };
  if (draft.edits.caption_text == null) draft.edits.caption_text = wordsIn(clip.start, clip.end).map((w) => w.word).join(" ");
  draft.originalText = draft.edits.caption_text;
  $("editor").hidden = false;
  document.body.style.overflow = "hidden";
  $("ed-title").textContent = `Clip ${clip.n} · ${clip.edits.title_text || clip.title}`;
  paintEditorForm(clip);
  paintScore(clip);
  paintPublish(clip);
  paintEditorStatus(true);
  drawTimeline();
}
function closeEditor() {
  editing = null; draft = null;
  $("editor").hidden = true;
  document.body.style.overflow = "";
  $("ed-video").pause();
}
$("ed-close").onclick = closeEditor;
$("new-project").onclick = () => { closeProject(); setTimeout(() => $("url").focus(), 50); };
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && editing) closeEditor(); });
function step(dir) {
  const i = project.clips.findIndex((c) => c.id === editing);
  const next = project.clips[(i + dir + project.clips.length) % project.clips.length];
  if (next) openEditor(next.id);
}
$("ed-prev").onclick = () => step(-1);
$("ed-next").onclick = () => step(1);

function allWords() { return (transcript?.segments || []).flatMap((s) => s.words || []); }
function wordsIn(a, b) { return allWords().filter((w) => w.start >= a - 0.05 && w.end <= b + 0.05); }

function paintEditorForm(clip) {
  const e = draft.edits;
  $("e-title").value = e.title_text || clip.title;
  $("e-show-title").checked = !!e.show_title;
  $("e-caps").checked = e.captions_on !== false;
  $("e-text").value = e.caption_text || "";
  $("e-silence").checked = !!e.remove_silence;
  $("e-norm").checked = e.normalize !== false;
  $("e-fades").checked = e.fades !== false;
  $("e-mark").value = e.watermark || "";
  styleTiles($("e-style"), e.style, (v) => (e.style = v));
  segmented($("e-aspect"), Object.fromEntries(ASPECTS.map((a) => [a, a])), e.aspect, (v) => (e.aspect = v));
  segmented($("e-framing"), EDIT_FRAMINGS, e.framing, (v) => { e.framing = v; $("e-manual-wrap").hidden = v !== "manual"; });
  $("e-manual-wrap").hidden = e.framing !== "manual";
  $("e-manual").value = e.manual_x ?? 0.5; fillRange($("e-manual"));
  $("o-manual").textContent = `${Math.round((e.manual_x ?? 0.5) * 100)}%`;
  $("e-manual").oninput = () => { e.manual_x = Number($("e-manual").value); $("o-manual").textContent = `${Math.round(e.manual_x * 100)}%`; fillRange($("e-manual")); };
  $("e-error").hidden = true;
  paintTrim();
}
function paintTrim() {
  $("t-start").textContent = clock(draft.start);
  $("t-end").textContent = clock(draft.end);
  $("t-len").textContent = `${(draft.end - draft.start).toFixed(1)}s`;
}
document.querySelectorAll("[data-nudge]").forEach((b) => b.addEventListener("click", () => {
  const [edge, d] = b.dataset.nudge.split(":");
  const dur = project.info?.duration || 1e9;
  draft[edge] = Math.max(0, Math.min(dur, +(draft[edge] + Number(d)).toFixed(2)));
  if (draft.end - draft.start < 3) draft[edge] = edge === "start" ? draft.end - 3 : draft.start + 3;
  refreshCaptionsForTrim(); paintTrim(); drawTimeline();
}));
function refreshCaptionsForTrim() {
  // When the trim changes and the captions were not hand-edited, follow the new range.
  if ($("e-text").value.trim() === (draft.originalText || "").trim()) {
    draft.originalText = wordsIn(draft.start, draft.end).map((w) => w.word).join(" ");
    $("e-text").value = draft.originalText;
  }
}

$("e-render").onclick = async () => {
  const clip = clipById(editing);
  const e = draft.edits;
  const typed = $("e-text").value.trim();
  const auto = wordsIn(draft.start, draft.end).map((w) => w.word).join(" ").trim();
  const payload = {
    start: draft.start, end: draft.end,
    edits: {
      style: e.style, aspect: e.aspect, framing: e.framing, manual_x: e.manual_x ?? 0.5,
      title_text: $("e-title").value.trim() === clip.title ? "" : $("e-title").value.trim(),
      show_title: $("e-show-title").checked, captions_on: $("e-caps").checked,
      caption_text: typed === auto ? null : typed,
      remove_silence: $("e-silence").checked, normalize: $("e-norm").checked, fades: $("e-fades").checked,
      watermark: $("e-mark").value.trim(),
    },
  };
  $("e-render").disabled = true;
  try {
    const updated = await api(`/api/jobs/${project.id}/clips/${clip.id}`, { method: "PATCH", json: payload });
    Object.assign(clip, updated);
    paintEditorStatus();
    poll();
    toast("Rendering your changes");
  } catch (error) {
    $("e-error").textContent = error.message; $("e-error").hidden = false;
  } finally { $("e-render").disabled = false; }
};
$("e-reset").onclick = async () => {
  try {
    const updated = await api(`/api/jobs/${project.id}/clips/${editing}/reset`, { method: "POST" });
    Object.assign(clipById(editing), updated);
    openEditor(editing);
    poll();
  } catch (error) { toast(error.message); }
};

let shownVersion = null;
function paintEditorStatus(force) {
  const clip = clipById(editing);
  if (!clip) return;
  const rendering = ["queued", "rendering"].includes(clip.render?.status);
  $("ed-busy").hidden = !rendering;
  $("e-render").disabled = rendering;
  if (clip.render?.status === "failed") { $("e-error").textContent = `Render failed: ${clip.render.error}`; $("e-error").hidden = false; }
  if (clip.file && (force || shownVersion !== `${clip.id}:${clip.version}`) && !rendering) {
    shownVersion = `${clip.id}:${clip.version}`;
    $("ed-video").src = media(project, clip.file) + `?v=${clip.version}`;
    $("ed-video").poster = media(project, clip.thumb) + `?v=${clip.version}`;
    $("ed-frame").style.aspectRatio = clip.size ? `${clip.size[0]}/${clip.size[1]}` : "9/16";
  }
  $("ed-dl").href = `/api/jobs/${project.id}/clips/${clip.id}/download`;
  $("ed-srt").href = `/api/jobs/${project.id}/clips/${clip.id}/download?kind=srt`;
  $("vote-up").setAttribute("aria-pressed", String(clip.feedback === 1));
  $("vote-down").setAttribute("aria-pressed", String(clip.feedback === -1));
  if (!clip.publish_busy) $("pub-regen").disabled = false;
  if (clip.publish && !clip.publish_busy && $("pub-body").dataset.v !== JSON.stringify(clip.publish).length + platform) paintPublish(clip);
}

/* timeline: loudness bars, word ticks, two snapping handles */
const tl = $("timeline");
let tlView = null, dragEdge = null;
function drawTimeline() {
  if (!editing) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = tl.clientWidth, h = tl.clientHeight;
  tl.width = w * dpr; tl.height = h * dpr;
  const g = tl.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  const dur = project.info?.duration || draft.end + 10;
  const pad = Math.max(8, (draft.end - draft.start) * 0.6);
  const a = Math.max(0, draft.start - pad), b = Math.min(dur, draft.end + pad);
  tlView = { a, b, w };
  const x = (t) => ((t - a) / (b - a)) * w;
  const energy = project.energy || [];
  g.fillStyle = "#3a3a40";
  for (let i = Math.floor(a * 2); i < Math.ceil(b * 2) && i < energy.length; i++) {
    const v = energy[i] / 100, bx = x(i / 2);
    g.fillRect(bx, h - 14 - v * (h - 28), Math.max(1, x((i + 1) / 2) - bx - 1), v * (h - 28));
  }
  g.fillStyle = "#6b6b72";
  for (const wd of allWords()) if (wd.start > a && wd.start < b) g.fillRect(x(wd.start), h - 8, 1, 4);
  for (const c of project.scene_cuts || []) if (c > a && c < b) { g.fillStyle = "#2f5bff"; g.fillRect(x(c), 0, 1, 6); }
  const sx = x(draft.start), ex = x(draft.end);
  g.fillStyle = "rgba(255,255,255,.08)"; g.fillRect(sx, 0, ex - sx, h);
  g.fillStyle = "rgba(255,255,255,.95)";
  g.fillRect(sx - 1, 0, 2, h); g.fillRect(ex - 1, 0, 2, h);
  g.fillRect(sx - 4, h / 2 - 9, 8, 18); g.fillRect(ex - 4, h / 2 - 9, 8, 18);
  g.font = "500 10px Geist Mono, monospace"; g.fillStyle = "#8b8b91";
  g.fillText(shortClock(a), 4, 12);
  const endLabel = shortClock(b);
  g.fillText(endLabel, w - g.measureText(endLabel).width - 4, 12);
}
function snap(t, edge) {
  const words = allWords();
  let best = t, bestD = 0.45;
  for (const w of words) {
    const cand = edge === "start" ? w.start - 0.1 : w.end + 0.2;
    const d = Math.abs(cand - t);
    if (d < bestD) { bestD = d; best = cand; }
  }
  return Math.max(0, +best.toFixed(2));
}
function tlTime(ev) {
  const r = tl.getBoundingClientRect();
  return tlView.a + ((ev.clientX - r.left) / r.width) * (tlView.b - tlView.a);
}
tl.addEventListener("pointerdown", (ev) => {
  if (!tlView) return;
  const t = tlTime(ev);
  dragEdge = Math.abs(t - draft.start) < Math.abs(t - draft.end) ? "start" : "end";
  tl.setPointerCapture(ev.pointerId);
});
tl.addEventListener("pointermove", (ev) => {
  if (!dragEdge) return;
  const t = snap(tlTime(ev), dragEdge);
  if (dragEdge === "start") draft.start = Math.min(t, draft.end - 3);
  else draft.end = Math.max(t, draft.start + 3);
  paintTrim(); drawTimeline();
});
const endDrag = () => { if (dragEdge) { dragEdge = null; refreshCaptionsForTrim(); } };
tl.addEventListener("pointerup", endDrag);
tl.addEventListener("pointercancel", endDrag);
window.addEventListener("resize", () => editing && drawTimeline());

/* tabs */
const TABS = [["t-edit", "p-edit"], ["t-score", "p-score"], ["t-pub", "p-pub"]];
TABS.forEach(([tab, panel]) => $(tab).addEventListener("click", () => {
  TABS.forEach(([t, p]) => { $(t).setAttribute("aria-selected", String(t === tab)); $(p).hidden = p !== panel; });
  if (panel === "p-edit") drawTimeline();
}));

/* score */
function paintScore(clip) {
  $("s-total").textContent = clip.score;
  $("s-reason").textContent = clip.reason + (clip.ai_score != null ? ` · AI judge gave ${clip.ai_score}/100` : "");
  const box = $("s-dims");
  box.innerHTML = "";
  for (const [key, label] of Object.entries(meta.dimensions)) {
    const d = clip.breakdown?.[key];
    if (!d) continue;
    const bar = el("i", { style: "width:0%" });
    box.append(el("div", { class: "dim" },
      el("div", { class: "dim-head" }, el("span", {}, label), el("span", {}, String(d.score))),
      el("div", { class: "dim-bar" }, bar),
      el("p", {}, (d.why || []).join(" · "))));
    requestAnimationFrame(() => (bar.style.width = `${d.score}%`));
  }
}
async function vote(value) {
  const clip = clipById(editing);
  const next = clip.feedback === value ? 0 : value;
  try {
    await api(`/api/jobs/${project.id}/clips/${clip.id}/feedback`, { method: "POST", json: { value: next } });
    clip.feedback = next;
    paintEditorStatus();
    toast(next === 1 ? "Noted. Future picks lean toward clips like this." : next === -1 ? "Noted. Future picks lean away from clips like this." : "Rating removed");
  } catch (e) { toast(e.message); }
}
$("vote-up").onclick = () => vote(1);
$("vote-down").onclick = () => vote(-1);

/* publish */
function paintPublish(clip) {
  segmented($("pub-platform"), PLATFORMS, platform, (v) => { platform = v; paintPublish(clipById(editing)); });
  const tone = $("pub-tone");
  if (!tone.options.length) for (const t of meta.tones) tone.add(new Option(t[0].toUpperCase() + t.slice(1), t));
  const body = $("pub-body");
  body.innerHTML = "";
  if (!clip.publish) { body.append(el("div", { class: "pub-field" }, el("p", { class: "mute" }, "Writing…"))); return; }
  body.dataset.v = JSON.stringify(clip.publish).length + platform;
  tone.value = clip.publish.tone || "curious";
  const copy = clip.publish.copy[platform] || {};
  const fields = Object.entries(copy).filter(([k]) => k !== "hashtags");
  if (copy.hashtags?.length) fields.push(["hashtags", copy.hashtags.join(" ")]);
  if (platform === "youtube" && clip.publish.copy.pinned_comment) fields.push(["pinned comment", clip.publish.copy.pinned_comment]);
  for (const [name, text] of fields) {
    const btn = el("button", { type: "button", class: "pub-copy" }, "Copy");
    btn.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; } catch { btn.textContent = "Select it"; }
      setTimeout(() => (btn.textContent = "Copy"), 1300);
    });
    body.append(el("div", { class: "pub-field" }, el("header", {}, el("span", {}, name), btn), el("p", {}, text)));
  }
  const eng = clip.publish.engine;
  $("pub-engine").textContent = eng === "template" ? "Written from a template. Connect OpenRouter or Ollama for AI-written copy." : `Written by ${eng === "openrouter" ? "OpenRouter" : eng === "ollama" ? "Ollama" : eng}. Edit before posting.`;
}
$("pub-regen").onclick = async () => {
  const clip = clipById(editing);
  $("pub-regen").disabled = true;
  try {
    await api(`/api/jobs/${project.id}/clips/${clip.id}/publish`, { method: "POST", json: { tone: $("pub-tone").value } });
    clip.publish_busy = true;
    $("pub-body").innerHTML = "";
    $("pub-body").append(el("div", { class: "pub-field" }, el("p", { class: "mute" }, "Rewriting…")));
    poll();
  } catch (e) { toast(e.message); $("pub-regen").disabled = false; }
};

/* ---------------------------------------------------------------- start */
$("year").textContent = new Date().getFullYear();
(async () => {
  try {
    await loadMeta();
    paintControls();
    await loadLibrary();
  } catch {
    setError("Clipzer's server is not answering. Start it with ./run.sh and reload this page.");
  }
  await minimumWait;
  $("loader").classList.add("gone");
  setTimeout(() => loaderGlobe.stop(), 700);
})();
