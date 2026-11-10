// Clipzer front end. Built by K S Pankaj.
const $ = (id) => document.getElementById(id);
const STAGES = ["import", "transcribe", "moments", "render"];
let mode = "link";
let pollTimer = null;
let current = null;

/* ---------- loading screen ---------- */
(function leader() {
  const count = $("count");
  let n = 3;
  const tick = setInterval(() => {
    n -= 1;
    if (n > 0) count.textContent = n;
    else clearInterval(tick);
  }, 500);
})();
const minimumWait = new Promise((done) => setTimeout(done, 1500));

/* ---------- drifting projector dust ---------- */
(function dust() {
  const canvas = $("dust");
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const ctx = canvas.getContext("2d");
  let specks = [];
  function size() {
    canvas.width = innerWidth;
    canvas.height = innerHeight;
    specks = Array.from({ length: Math.min(70, Math.floor(innerWidth / 18)) }, () => ({
      x: Math.random() * canvas.width, y: Math.random() * canvas.height,
      r: Math.random() * 1.6 + 0.3, vx: (Math.random() - 0.5) * 0.15, vy: Math.random() * 0.2 + 0.03,
      a: Math.random() * 0.5 + 0.1,
    }));
  }
  function frame() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const s of specks) {
      s.x += s.vx; s.y += s.vy;
      if (s.y > canvas.height) { s.y = -4; s.x = Math.random() * canvas.width; }
      ctx.fillStyle = `rgba(255, 214, 150, ${s.a})`;
      ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, 6.3); ctx.fill();
    }
    requestAnimationFrame(frame);
  }
  addEventListener("resize", size);
  size(); frame();
})();

/* ---------- helpers ---------- */
async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}
function showError(text) {
  const box = $("form-error");
  box.textContent = text || "";
  box.hidden = !text;
}
function clock(seconds) {
  const m = Math.floor(seconds / 60), s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/* ---------- status chips ---------- */
async function loadHealth() {
  try {
    const h = await api("/api/health");
    const chips = [
      [h.ffmpeg, h.ffmpeg ? `ffmpeg · ${h.encoder === "h264_nvenc" ? "GPU encode" : "CPU encode"}` : "ffmpeg missing"],
      [h.whisper, h.whisper ? `Whisper ${h.whisper_model}` : "Whisper not installed"],
      [h.ai_picker, h.ai_picker ? "AI picker on" : "Built-in picker (no key)"],
    ];
    $("chips").innerHTML = "";
    for (const [ok, label] of chips) {
      const li = document.createElement("li");
      li.className = ok ? "on" : "off";
      li.textContent = label;
      $("chips").append(li);
    }
    const style = $("style");
    style.innerHTML = "";
    for (const [key, label] of Object.entries(h.styles)) style.add(new Option(label, key));
  } catch {
    showError("The Clipzer server is not answering. Start it with run.sh (or run.bat) and reload this page.");
  }
}

/* ---------- tabs and file drop ---------- */
function setMode(next) {
  mode = next;
  $("tab-link").setAttribute("aria-selected", next === "link");
  $("tab-file").setAttribute("aria-selected", next === "file");
  $("pane-link").hidden = next !== "link";
  $("pane-file").hidden = next !== "file";
}
$("tab-link").onclick = () => setMode("link");
$("tab-file").onclick = () => setMode("file");
const drop = $("drop");
["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (ev) => {
  if (ev.dataTransfer.files.length) { $("file").files = ev.dataTransfer.files; nameFile(); }
});
$("file").addEventListener("change", nameFile);
function nameFile() {
  const file = $("file").files[0];
  $("drop-title").textContent = file ? `${file.name} · ${(file.size / 1048576).toFixed(0)} MB` : "Drop a video here, or tap to choose";
}

/* ---------- submit ---------- */
$("composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  showError("");
  const url = $("url").value.trim();
  const file = $("file").files[0];
  if (mode === "link" && !url) return showError("Paste a video link first.");
  if (mode === "file" && !file) return showError("Choose a video file first.");
  if (!$("rights").checked) return showError("Tick the box to confirm you are allowed to clip this video.");

  const [min, max] = $("length").value.split("-");
  const body = new FormData();
  body.append("rights", "true");
  if (mode === "link") body.append("url", url); else body.append("file", file);
  body.append("num_clips", $("num_clips").value);
  body.append("min_len", min);
  body.append("max_len", max);
  body.append("style", $("style").value);
  body.append("framing", $("framing").value);
  body.append("language", $("language").value);
  body.append("show_title", $("show_title").checked ? "true" : "false");

  const button = $("go");
  button.disabled = true;
  button.firstElementChild.textContent = mode === "file" ? "Uploading…" : "Starting…";
  try {
    const job = await api("/api/jobs", { method: "POST", body });
    watch(job.id);
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
    button.firstElementChild.textContent = "Make my clips";
  }
});

/* ---------- progress ---------- */
function watch(id) {
  current = id;
  clearInterval(pollTimer);
  $("progress").hidden = false;
  $("results").hidden = true;
  $("grid").innerHTML = "";
  $("progress").scrollIntoView({ behavior: "smooth", block: "center" });
  const poll = async () => {
    try {
      const job = await api(`/api/jobs/${id}`);
      if (current === id) paint(job);
      if (job.status === "done" || job.status === "failed") { clearInterval(pollTimer); loadJobs(); }
    } catch { /* server busy: try again on the next tick */ }
  };
  poll();
  pollTimer = setInterval(poll, 1500);
}

function paint(job) {
  const stageIndex = job.status === "done" ? STAGES.length : STAGES.indexOf(job.stage);
  const overall = job.status === "done" ? 100 : Math.round(((Math.max(stageIndex, 0) + (job.progress || 0) / 100) / STAGES.length) * 100);
  $("job-name").textContent = job.name || "Working";
  $("job-pct").textContent = `${String(overall).padStart(2, "0")}%`;
  $("strip-fill").style.width = `${overall}%`;
  $("progress").classList.toggle("failed", job.status === "failed");
  $("job-msg").textContent = job.status === "failed" ? `Stopped: ${job.error}` : job.message;
  document.querySelectorAll("#steps li").forEach((li, i) => {
    li.className = i < stageIndex ? "done" : i === stageIndex && job.status !== "failed" ? "now" : "";
  });
  if (job.clips && job.clips.length) showClips(job);
}

function showClips(job) {
  const grid = $("grid");
  if (grid.dataset.job === job.id && grid.children.length === job.clips.length) return;
  grid.dataset.job = job.id;
  $("results").hidden = false;
  $("results-note").textContent = job.engine === "ai" ? "Ranked by the AI picker, best first." : "Ranked by the built-in picker, best first.";
  for (let i = grid.children.length; i < job.clips.length; i++) {
    const clip = job.clips[i];
    const card = $("card").content.firstElementChild.cloneNode(true);
    const base = `/media/${job.id}/`;
    const video = card.querySelector("video");
    video.src = base + encodeURIComponent(clip.file);
    video.poster = base + encodeURIComponent(clip.thumb);
    card.querySelector(".score").textContent = `${clip.score}/100`;
    card.querySelector("h3").textContent = clip.title || `Clip ${i + 1}`;
    card.querySelector(".reason").textContent = clip.reason;
    card.querySelector(".meta").textContent = `${clock(clip.start)} → ${clock(clip.end)} · ${clip.duration}s · ${clip.framing}`;
    const link = card.querySelector("a.btn");
    link.href = video.src;
    link.download = clip.file;
    const copy = card.querySelector("button");
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(clip.title); copy.textContent = "Copied"; }
      catch { copy.textContent = "Copy failed"; }
      setTimeout(() => (copy.textContent = "Copy title"), 1400);
    };
    card.style.animationDelay = `${(i % 6) * 60}ms`;
    grid.append(card);
  }
}

/* ---------- earlier jobs ---------- */
async function loadJobs() {
  let jobs = [];
  try { jobs = await api("/api/jobs"); } catch { return; }
  $("library").hidden = jobs.length === 0;
  const list = $("jobs");
  list.innerHTML = "";
  for (const job of jobs) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = job.name || job.id;
    const state = document.createElement("span");
    state.className = `state ${job.status}`;
    state.textContent = job.status === "done" ? `${job.clips.length} clips` : job.status;
    const actions = document.createElement("span");
    actions.className = "row-actions";
    const open = document.createElement("button");
    open.className = "btn ghost"; open.type = "button"; open.textContent = "Open";
    open.onclick = () => watch(job.id);
    const remove = document.createElement("button");
    remove.className = "btn ghost"; remove.type = "button"; remove.textContent = "Delete";
    remove.onclick = async () => {
      if (remove.dataset.sure !== "1") { remove.dataset.sure = "1"; remove.textContent = "Tap again to delete"; return; }
      try { await api(`/api/jobs/${job.id}`, { method: "DELETE" }); } catch (error) { showError(error.message); }
      if (current === job.id) { $("progress").hidden = true; $("results").hidden = true; }
      loadJobs();
    };
    actions.append(open, remove);
    li.append(name, state, actions);
    list.append(li);
  }
  const running = jobs.find((j) => j.status === "running" || j.status === "queued");
  if (running && !current) watch(running.id);
}

/* ---------- start ---------- */
$("year").textContent = new Date().getFullYear();
Promise.all([loadHealth(), loadJobs(), minimumWait]).finally(() => $("loader").classList.add("gone"));
