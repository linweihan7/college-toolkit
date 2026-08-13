"use strict";

const $ = (id) => document.getElementById(id);
const api = (p, o) => fetch(p, o).then((r) => (r.ok ? r.json() : r.json().then((e) => Promise.reject(e))));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtTime = (sec) => {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${p(h)}:${p(m)}:${p(s)}` : `${p(m)}:${p(s)}`;
};

let CAPS = null;
let currentMeetingId = null;
let pollTimer = null;
let SPEAKER_NAMES = {};

// Display precedence: manual edit > AI-cleaned > raw ASR.
const displayText = (s) => s.edited || s.clean || s.text || "";
const spName = (raw) => (raw ? (SPEAKER_NAMES[raw] || raw) : "");

/* ============================ Views ============================ */
function show(view) {
  ["newView", "procView", "meetingView"].forEach((v) => $(v).classList.toggle("hidden", v !== view));
}

/* ============================ Capabilities ============================ */
async function loadCaps() {
  CAPS = await api("/api/config");
  const eng = $("optEngine");
  eng.innerHTML = "";
  for (const [key, info] of Object.entries(CAPS.engines)) {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = (key === "local" ? "本機 Whisper（隱私）" : "雲端 API") +
      (info.available ? "" : "（無法使用）");
    opt.disabled = !info.available;
    eng.appendChild(opt);
  }
  eng.value = CAPS.engines[CAPS.default_engine]?.available ? CAPS.default_engine
    : (CAPS.engines.local.available ? "local" : "cloud");

  const diar = CAPS.diarization;
  $("optDiarize").checked = diar.available;
  $("optDiarize").disabled = !diar.available;
  $("diarNote").textContent = diar.available
    ? (diar.backend === "offline" ? "（離線，免金鑰）" : "（pyannote）")
    : `(${diar.reason})`;

  const live = CAPS.live || { available: false };
  $("liveCaps").checked = live.available;
  $("liveCaps").disabled = !live.available;
  $("liveNote").textContent = live.available ? "（邊講邊出字）" : "（需本機引擎）";

  const ai = firstAiProvider();
  $("aiClean").disabled = !ai || !live.available;
  if (!ai) $("aiClean").checked = false;
  $("aiCleanNote").textContent = ai ? "（AI 邊聽邊修正字幕）" : "（需 Claude／GPT／Gemini 金鑰，Gemini 免費）";

  // Summary AI providers (Claude / GPT / Gemini).
  const provs = CAPS.summarization.providers;
  const provLabels = { claude: "Claude", openai: "GPT (OpenAI)", gemini: "Gemini", local: "離線摘要（免金鑰）" };
  const provSel = $("optSummaryProvider");
  provSel.innerHTML = "";
  Object.entries(provs).forEach(([k, info]) => {
    const o = document.createElement("option");
    o.value = k;
    o.textContent = (provLabels[k] || k) + (info.available ? "" : "（無法使用）");
    o.disabled = !info.available;
    provSel.appendChild(o);
  });
  const pick = provs[CAPS.summarization.default]?.available
    ? CAPS.summarization.default
    : Object.keys(provs).find((k) => provs[k].available);
  if (pick) provSel.value = pick;
  $("provNote").textContent = pick ? "" : "（尚未設定 API 金鑰）";

  const chips = [
    ["本機 Whisper", CAPS.engines.local.available],
    ["雲端 API", CAPS.engines.cloud.available],
    ["發言者", CAPS.diarization.available],
    ["Claude", provs.claude.available],
    ["GPT", provs.openai.available],
    ["Gemini", provs.gemini.available],
  ];
  $("capsBar").innerHTML = chips.map(([n, ok]) =>
    `<span class="chip ${ok ? "on" : "off"}">${ok ? "●" : "○"} ${n}</span>`).join("");
}

/* ============================ Meeting list ============================ */
async function loadList() {
  const items = await api("/api/meetings");
  const el = $("meetingList");
  if (!items.length) { el.innerHTML = `<p class="muted small" style="padding:8px">尚無會議。</p>`; return; }
  el.innerHTML = items.map((m) => `
    <div class="item ${m.id === currentMeetingId ? "active" : ""}" data-id="${m.id}">
      <div class="t">${esc(m.title)}${m.series ? ` <span class="series-tag">${esc(m.series)}</span>` : ""}</div>
      <div class="m"><span class="dot ${m.status}"></span>${esc(statusLabel(m.status))}
        ${m.duration ? " · " + fmtTime(m.duration) : ""} · ${new Date(m.created_at * 1000).toLocaleDateString()}</div>
    </div>`).join("");
  el.querySelectorAll(".item").forEach((n) => n.onclick = () => openMeeting(n.dataset.id));
}
const STATUS_LABELS = { queued: "排隊中", processing: "處理中", done: "完成", error: "錯誤" };
const statusLabel = (s) => STATUS_LABELS[s] || s;

/* ============================ Recording ============================ */
let mediaRecorder = null, chunks = [], recStream = null, audioCtx = null, meterCtx = null,
  analyser = null, extraStreams = [], timerInt = null, meterRAF = null, recStart = 0;
let liveProcessor = null, liveBuf = [], liveTimer = null, liveBusy = false, liveSR = 16000;
let aiCleanActive = false, aiCleanBuf = [], aiCleanTimer = null, aiCleanBusy = false, aiCleanTail = "";

function firstAiProvider() {
  if (!CAPS) return "";
  const p = CAPS.summarization.providers;
  return ["claude", "openai", "gemini"].find((k) => p[k] && p[k].available) || "";
}

// Keep audio contexts running if the tab is backgrounded during a long meeting.
function resumeCtxs() {
  [audioCtx, meterCtx].forEach((c) => { if (c && c.state === "suspended") c.resume().catch(() => {}); });
}

async function startRecording() {
  try {
    const includeSystem = $("sysAudio").checked;
    const mic = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
    });
    extraStreams = [mic];

    // Record the mic stream DIRECTLY (no AudioContext in the record path) so the
    // recording keeps running for any length even when the tab is in background.
    // Only build a mixer when the user also captures system/tab audio.
    let recordStream = mic;
    if (includeSystem) {
      const disp = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      disp.getVideoTracks().forEach((t) => t.stop());
      extraStreams.push(disp);
      if (disp.getAudioTracks().length) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const dest = audioCtx.createMediaStreamDestination();
        audioCtx.createMediaStreamSource(mic).connect(dest);
        audioCtx.createMediaStreamSource(disp).connect(dest);
        recordStream = dest.stream;
      } else {
        alert("未分享系統聲音 — 將僅錄製麥克風。");
      }
    }

    // Level meter (and live captions) run on their OWN context, tapping the
    // record stream. If it gets suspended in the background, only the meter
    // pauses — never the recording. Prefer 16 kHz so live PCM needs no resample.
    try { meterCtx = new AudioContext({ sampleRate: 16000 }); }
    catch (e) { meterCtx = new (window.AudioContext || window.webkitAudioContext)(); }
    analyser = meterCtx.createAnalyser();
    analyser.fftSize = 512;
    meterCtx.createMediaStreamSource(recordStream).connect(analyser);

    if ($("liveCaps").checked && CAPS && CAPS.live && CAPS.live.available) startLive(recordStream);

    recStream = recordStream;
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
    mediaRecorder = new MediaRecorder(recordStream, mime ? { mimeType: mime } : undefined);
    chunks = [];
    // Flush a chunk every 5 s so a very long meeting streams to memory steadily.
    mediaRecorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    mediaRecorder.onstop = onRecStop;
    mediaRecorder.start(5000);
    document.addEventListener("visibilitychange", resumeCtxs);

    recStart = Date.now();
    $("recBtn").disabled = true; $("stopBtn").disabled = false;
    $("recBtn").textContent = "● 錄音中…";
    timerInt = setInterval(() => $("timer").textContent = fmtTime((Date.now() - recStart) / 1000), 250);
    drawMeter();
  } catch (err) {
    alert("無法開始錄音：" + err.message);
    cleanupRecording();
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
}

function onRecStop() {
  const blob = new Blob(chunks, { type: chunks[0]?.type || "audio/webm" });
  cleanupRecording();
  uploadAudio(blob, `recording-${Date.now()}.webm`);
}

function cleanupRecording() {
  clearInterval(timerInt); cancelAnimationFrame(meterRAF);
  document.removeEventListener("visibilitychange", resumeCtxs);
  clearInterval(liveTimer); liveTimer = null;
  clearInterval(aiCleanTimer); aiCleanTimer = null;
  if (liveProcessor) { try { liveProcessor.disconnect(); } catch (e) {} liveProcessor.onaudioprocess = null; liveProcessor = null; }
  liveBuf = []; liveBusy = false;
  aiCleanBuf = []; aiCleanBusy = false; aiCleanActive = false;
  $("liveBox").classList.add("hidden");
  $("aiBox").classList.add("hidden");
  extraStreams.forEach((s) => s.getTracks().forEach((t) => t.stop()));
  extraStreams = [];
  if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
  if (meterCtx) { meterCtx.close().catch(() => {}); meterCtx = null; }
  $("recBtn").disabled = false; $("stopBtn").disabled = true;
  $("recBtn").textContent = "● 開始錄音";
  $("timer").textContent = "00:00";
  const ctx = $("meter").getContext("2d");
  ctx.clearRect(0, 0, $("meter").width, $("meter").height);
}

function drawMeter() {
  const canvas = $("meter"), ctx = canvas.getContext("2d");
  const buf = new Uint8Array(analyser.frequencyBinCount);
  const draw = () => {
    meterRAF = requestAnimationFrame(draw);
    analyser.getByteFrequencyData(buf);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const bars = 48, step = Math.floor(buf.length / bars);
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent");
    for (let i = 0; i < bars; i++) {
      const v = buf[i * step] / 255;
      const h = Math.max(2, v * canvas.height);
      ctx.fillStyle = accent;
      ctx.globalAlpha = 0.35 + v * 0.65;
      ctx.fillRect(i * (canvas.width / bars) + 1, (canvas.height - h) / 2, canvas.width / bars - 2, h);
    }
    ctx.globalAlpha = 1;
  };
  draw();
}

/* ============================ Live captions ============================ */
function capTo(box, text, cls) {
  const el = document.createElement("div");
  el.className = "cap" + (cls ? " " + cls : "");
  el.textContent = text;
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
  return el;
}

function startLive(stream) {
  liveSR = meterCtx.sampleRate;
  const src = meterCtx.createMediaStreamSource(stream);
  liveProcessor = meterCtx.createScriptProcessor(4096, 1, 1);
  src.connect(liveProcessor);
  const sink = meterCtx.createGain(); sink.gain.value = 0;         // silent sink keeps the node processing
  liveProcessor.connect(sink); sink.connect(meterCtx.destination);
  liveBuf = [];
  liveProcessor.onaudioprocess = (e) => liveBuf.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  $("liveCaptions").innerHTML = "";
  $("liveBox").classList.remove("hidden");
  liveTimer = setInterval(flushLive, 3500);

  // AI proofreading of the live captions, if a key is set and the toggle is on.
  const prov = $("aiClean").checked ? firstAiProvider() : "";
  aiCleanActive = !!prov;
  if (aiCleanActive) {
    aiCleanBuf = []; aiCleanTail = "";
    $("aiProvLabel").textContent = { claude: "Claude", openai: "GPT", gemini: "Gemini" }[prov] || prov;
    $("aiCaptions").innerHTML = "";
    $("aiBox").classList.remove("hidden");
    aiCleanTimer = setInterval(flushClean, 9000);   // batch a few captions for context
  }
}

async function flushClean() {
  if (aiCleanBusy || !aiCleanBuf.length) return;
  const rough = aiCleanBuf.join(" ").trim();
  aiCleanBuf = [];
  if (!rough) return;
  aiCleanBusy = true;
  const pend = capTo($("aiCaptions"), "…", "pending");
  try {
    const r = await fetch(`/api/clean?provider=${firstAiProvider()}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: rough, context: aiCleanTail }),
    });
    const j = await r.json();
    pend.remove();
    if (j.text) { capTo($("aiCaptions"), j.text); aiCleanTail = j.text; }
  } catch (e) {
    pend.remove();
  }
  aiCleanBusy = false;
}

async function flushLive() {
  if (liveBusy) return;
  const total = liveBuf.reduce((n, a) => n + a.length, 0);
  if (total < liveSR * 2) return;                                  // wait for >= 2 s of audio
  const win = new Float32Array(total);
  let off = 0;
  for (const a of liveBuf) { win.set(a, off); off += a.length; }
  liveBuf = [];
  const pcm = new Int16Array(win.length);
  for (let i = 0; i < win.length; i++) { const s = Math.max(-1, Math.min(1, win[i])); pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff; }

  liveBusy = true;
  const pend = addPending();
  try {
    const r = await fetch(
      `/api/transcribe_chunk?sample_rate=${Math.round(liveSR)}&language=${encodeURIComponent($("optLanguage").value)}`,
      { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: pcm.buffer }
    );
    const j = await r.json();
    pend.remove();
    if (j.text) appendLiveLine(j.text);
  } catch (e) {
    pend.remove();
  }
  liveBusy = false;
}

function appendLiveLine(text) {
  capTo($("liveCaptions"), text);
  if (aiCleanActive) aiCleanBuf.push(text);        // feed the AI proofreader
}

function addPending() {
  return capTo($("liveCaptions"), "…", "pending");
}

/* ============================ Upload + processing ============================ */
async function uploadAudio(blob, filename) {
  if (!blob || blob.size === 0) {
    alert("錄音／檔案是空的，未儲存。請確認麥克風權限或檔案內容後再試一次。");
    show("newView");
    return;
  }
  const opts = {
    title: $("optTitle").value.trim(),
    series: $("optSeries").value.trim(),
    engine: $("optEngine").value,
    language: $("optLanguage").value,
    summary_language: $("optSummaryLang").value,
    summary_provider: $("optSummaryProvider").value || "",
    diarize: $("optDiarize").checked,
    num_speakers: $("optNumSpeakers").value ? Number($("optNumSpeakers").value) : null,
    vocabulary: $("optVocab").value.trim(),
  };
  const fd = new FormData();
  fd.append("audio", blob, filename);
  fd.append("options", JSON.stringify(opts));

  show("procView");
  $("procTitle").textContent = "處理中…";
  $("progressBar").style.width = "5%";
  $("procStage").textContent = "上傳中…";
  try {
    const { id } = await api("/api/meetings", { method: "POST", body: fd });
    currentMeetingId = id;
    pollStatus(id);
    loadList();
  } catch (e) {
    const msg = e.detail || e.message || JSON.stringify(e);
    $("procStage").textContent = "錯誤：" + msg;
    alert("儲存失敗：" + msg);
    show("newView");
  }
}

function pollStatus(id) {
  clearInterval(pollTimer);
  const t0 = Date.now();
  pollTimer = setInterval(async () => {
    let s;
    try { s = await api(`/api/meetings/${id}/status`); } catch { return; }
    $("progressBar").style.width = (s.progress || 0) + "%";
    const elapsed = "已用 " + fmtTime((Date.now() - t0) / 1000);
    const audio = s.duration ? " · 音訊 " + fmtTime(s.duration) : "";
    $("procStage").textContent = (s.stage || "") + " · " + elapsed + audio;
    $("procTitle").textContent = s.title && s.title !== "未命名會議" ? s.title : "處理中…";
    if (s.status === "done" || s.status === "error") {
      clearInterval(pollTimer);
      loadList();
      if (id === currentMeetingId) openMeeting(id);
    }
  }, 1000);
}

/* ============================ Meeting detail ============================ */
async function openMeeting(id) {
  currentMeetingId = id;
  loadList();
  const m = await api(`/api/meetings/${id}`);
  if (m.status === "processing" || m.status === "queued") { show("procView"); pollStatus(id); return; }
  show("meetingView");
  renderMeeting(m);
}

function renderMeeting(m) {
  $("mTitle").textContent = m.title;
  const r = m.result || {};
  SPEAKER_NAMES = r.speaker_names || {};
  // AI proofreading needs an LLM key — make that visible rather than silently alerting.
  const aiOk = !!firstAiProvider();
  $("cleanupBtn").disabled = !aiOk;
  $("cleanupBtn").title = aiOk ? "用 AI 修正整份逐字稿" : "需在 .env 設定 Claude／GPT／Gemini 金鑰（Gemini 免費）";
  const langName = { en: "English", zh: "中文", "": "—" }[r.language] || r.language;
  const badges = [
    new Date(m.created_at * 1000).toLocaleString(),
    r.duration ? fmtTime(r.duration) : null,
    m.engine === "cloud" ? "雲端 API" : "本機 Whisper",
    langName ? "語言：" + langName : null,
    r.diarized ? `${r.speakers.length} 位發言者` : null,
  ].filter(Boolean);
  $("mBadges").innerHTML = badges.map((b) => `<span class="badge">${esc(b)}</span>`).join("");

  $("player").src = `/api/meetings/${m.id}/audio`;

  const errBox = $("errorBox");
  if (m.status === "error") { errBox.classList.remove("hidden"); errBox.textContent = m.error || "Processing failed."; }
  else errBox.classList.add("hidden");

  renderSummary(r.summary);
  renderTranscript(r.segments || []);
  renderMinutes(r.summary ? r.summary.minutes_markdown : "");
  switchTab("summary");
}

const PROV_LABELS = { claude: "Claude", openai: "GPT", gemini: "Gemini", local: "離線摘要" };

function availableProviders() {
  return CAPS ? Object.entries(CAPS.summarization.providers).filter(([, v]) => v.available).map(([k]) => k) : [];
}

function summaryToolbar(hasSummary) {
  const avail = availableProviders();
  if (!avail.length) return "";
  const opts = avail.map((k) => `<option value="${k}">${PROV_LABELS[k] || k}</option>`).join("");
  const cmp = avail.length >= 2 ? `<button id="cmpBtn" class="ghost">⇄ 比較 AI</button>` : "";
  return `<div class="sum-toolbar">
    <select id="genProv" class="miniSel">${opts}</select>
    <button id="genBtn" class="primary">${hasSummary ? "重新生成摘要" : "生成摘要"}</button>
    ${cmp}
  </div>`;
}

function wireSummaryToolbar() {
  if ($("genBtn")) $("genBtn").onclick = generateSummary;
  if ($("cmpBtn")) $("cmpBtn").onclick = compareProviders;
}

async function compareProviders() {
  $("tab-summary").innerHTML = `<p class="muted">比較中…（分別呼叫各 AI，請稍候）</p>`;
  try {
    const r = await api(`/api/meetings/${currentMeetingId}/compare`, { method: "POST" });
    renderComparison(r.results || {}, r.errors || {});
  } catch (e) {
    alert("比較失敗：" + (e.detail || e.message || JSON.stringify(e)));
    openMeeting(currentMeetingId);
  }
}

function renderComparison(results, errors) {
  const el = $("tab-summary");
  const cols = Object.entries(results).map(([p, s]) => `
    <div class="cmp-col">
      <h3>${PROV_LABELS[p] || p}</h3>
      <p class="sum-lead">${esc(s.summary || "")}</p>
      ${s.highlights && s.highlights.length ? `<ul class="hl-list">${s.highlights.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>` : ""}
      ${s.action_items && s.action_items.length ? `<h4>行動項目</h4><ul class="hl-list">${s.action_items.map((a) => `<li>${esc(a.task)}${a.owner ? " — " + esc(a.owner) : ""}</li>`).join("")}</ul>` : ""}
    </div>`).join("");
  const errHtml = Object.entries(errors).map(([p, m]) => `<div class="error">${PROV_LABELS[p] || p}：${esc(m)}</div>`).join("");
  el.innerHTML = `<div class="sum-toolbar"><button id="backBtn" class="ghost">← 返回摘要</button></div>${errHtml}<div class="cmp-grid">${cols}</div>`;
  $("backBtn").onclick = () => openMeeting(currentMeetingId);
}

async function generateSummary() {
  const btn = $("genBtn"), prov = $("genProv") ? $("genProv").value : "";
  if (btn) { btn.disabled = true; btn.textContent = "生成中…（呼叫 " + (PROV_LABELS[prov] || prov) + "）"; }
  try {
    await api(`/api/meetings/${currentMeetingId}/resummarize?provider=${encodeURIComponent(prov)}`, { method: "POST" });
    const m = await api(`/api/meetings/${currentMeetingId}`);
    renderMeeting(m); switchTab("summary"); loadList();
  } catch (e) {
    alert("生成摘要失敗：" + (e.detail || e.message || JSON.stringify(e)));
    if (btn) { btn.disabled = false; btn.textContent = "生成摘要"; }
  }
}

function renderSummary(s) {
  const el = $("tab-summary");
  if (!s) {
    if (availableProviders().length) {
      el.innerHTML = summaryToolbar(false) + `<p class="muted">尚未生成摘要。選擇 AI 後按「生成摘要」。</p>`;
    } else {
      el.innerHTML = `<p class="muted">尚無摘要。請在 .env 設定 Claude／GPT／Gemini 任一 API 金鑰（Gemini 有免費額度）以啟用重點摘要。</p>`;
    }
    wireSummaryToolbar();
    return;
  }
  const provTag = s._provider ? `<span class="badge">由 ${PROV_LABELS[s._provider] || s._provider} 生成</span>` : "";
  const block = (title, body) => body ? `<div class="sum-block"><h3>${title}</h3>${body}</div>` : "";
  const list = (arr, cls) => arr && arr.length ? `<ul class="${cls}">${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  const ai = s.action_items && s.action_items.length
    ? `<table class="ai"><thead><tr><th>事項</th><th>負責人</th><th>期限</th></tr></thead><tbody>${
        s.action_items.map((a) => {
          const task = (a.ts !== undefined && a.ts !== null)
            ? `<span class="ailink" data-t="${a.ts}" title="跳到此處">${esc(a.task)}</span>` : esc(a.task);
          return `<tr><td>${task}</td><td>${esc(a.owner)}</td><td>${esc(a.due)}</td></tr>`;
        }).join("")
      }</tbody></table>` : "";
  const topics = s.topics && s.topics.length
    ? s.topics.map((t) => `<div class="topic"><h4>${esc(t.title)}</h4><p>${esc(t.summary)}</p></div>`).join("") : "";

  el.innerHTML =
    `<div class="sum-head">${provTag}${summaryToolbar(true)}</div>` +
    block("摘要", s.summary ? `<p class="sum-lead">${esc(s.summary)}</p>` : "") +
    block("重點", list(s.highlights, "hl-list")) +
    block("決議", list(s.decisions, "dec-list")) +
    block("行動項目", ai) +
    block("討論主題", topics);
  wireSummaryToolbar();
  el.querySelectorAll(".ailink").forEach((n) => n.onclick = () => {
    const p = $("player"); if (p) { p.currentTime = Number(n.dataset.t); p.play(); }
  });
}

let transcriptView = "clean";   // clean | raw | compare (only when AI-cleaned)

function renderTranscript(segments) {
  const body = $("transcriptBody");
  if (!segments.length) { body.innerHTML = `<p class="muted">尚無逐字稿。</p>`; return; }
  const hasClean = segments.some((s) => s.clean);
  const speakers = [...new Set(segments.map((s) => s.speaker).filter(Boolean))];
  const spanOf = (s) => {
    if (!s.speaker) return "";
    return `<span class="spk spk-${speakers.indexOf(s.speaker) % 6}" data-raw="${esc(s.speaker)}" title="點擊重新命名">${esc(spName(s.speaker))}</span> `;
  };
  const toolbar = hasClean ? `<div class="tview">
    <button data-v="clean" class="${transcriptView === "clean" ? "active" : ""}">AI 校對</button>
    <button data-v="raw" class="${transcriptView === "raw" ? "active" : ""}">原始</button>
    <button data-v="compare" class="${transcriptView === "compare" ? "active" : ""}">對照</button>
  </div>` : "";

  const rows = segments.map((s, i) => {
    const spk = spanOf(s), raw = esc(s.text), disp = esc(displayText(s));
    let inner;
    if (hasClean && transcriptView === "compare") {
      inner = `<div class="cmp2"><div class="raw">${spk}${raw}</div><div class="cln">${spk}${disp}</div></div>`;
    } else {
      const show = transcriptView === "raw" ? raw : disp;
      const lc = (s.logprob !== undefined && s.logprob < -0.9 && !s.edited) ? " lowconf" : "";
      const tip = lc ? "辨識信心較低，建議核對；雙擊可編輯" : "雙擊可編輯";
      inner = `${spk}<span class="txt${lc}" data-i="${i}" title="${tip}">${show}</span>`;
    }
    return `<div class="turn"><span class="ts" data-t="${s.start}">${fmtTime(s.start)}</span>
      <div class="body">${inner}</div></div>`;
  }).join("");

  body.innerHTML = toolbar + rows;
  body.querySelectorAll(".ts").forEach((n) => n.onclick = () => {
    const p = $("player"); p.currentTime = Number(n.dataset.t); p.play();
  });
  body.querySelectorAll(".tview button").forEach((b) => b.onclick = () => {
    transcriptView = b.dataset.v; renderTranscript(segments);
  });
  body.querySelectorAll(".spk").forEach((n) => n.onclick = () => renameSpeaker(n.dataset.raw, segments));
  body.querySelectorAll(".txt").forEach((n) => n.ondblclick = () => editLine(Number(n.dataset.i), segments, n));
}

async function renameSpeaker(raw, segments) {
  const name = prompt(`為「${raw}」命名（清空即還原）：`, SPEAKER_NAMES[raw] || "");
  if (name === null) return;
  const names = { ...SPEAKER_NAMES };
  if (name.trim()) names[raw] = name.trim(); else delete names[raw];
  try {
    await api(`/api/meetings/${currentMeetingId}/speakers`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ names }),
    });
    SPEAKER_NAMES = names; renderTranscript(segments); loadList();
  } catch (e) { alert("命名失敗：" + (e.detail || e.message || JSON.stringify(e))); }
}

function editLine(i, segments, span) {
  const cur = displayText(segments[i]);
  const ta = document.createElement("textarea");
  ta.className = "lineEdit"; ta.value = cur;
  span.replaceWith(ta); ta.focus(); ta.setSelectionRange(cur.length, cur.length);
  let done = false;
  const save = async () => {
    if (done) return; done = true;
    const text = ta.value.trim();
    if (text && text !== cur) {
      try {
        await api(`/api/meetings/${currentMeetingId}/segment`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ index: i, text }),
        });
        segments[i].edited = text;
      } catch (e) { alert("儲存失敗：" + (e.detail || e.message)); }
    }
    renderTranscript(segments);
  };
  ta.onblur = save;
  ta.onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ta.blur(); }
    if (e.key === "Escape") { done = true; renderTranscript(segments); }
  };
}

function renderMinutes(md) {
  $("tab-minutes").innerHTML = md ? mdToHtml(md) : `<p class="muted">尚未產生會議記錄。</p>`;
}

/* ---- transcript search ---- */
$("tSearch").addEventListener("input", (e) => {
  const q = e.target.value.trim().toLowerCase();
  $("transcriptBody").querySelectorAll(".turn").forEach((turn) => {
    const body = turn.querySelector(".body");
    const text = body.textContent;
    if (!q) { body.innerHTML = body.innerHTML.replace(/<\/?mark>/g, ""); turn.style.display = ""; return; }
    const hit = text.toLowerCase().includes(q);
    turn.style.display = hit ? "" : "none";
    if (hit) {
      const re = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi");
      // rebuild safely: escape then wrap matches
      body.innerHTML = esc(text).replace(re, "<mark>$1</mark>");
    }
  });
});

/* ============================ Tabs ============================ */
function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  ["summary", "transcript", "minutes"].forEach((t) => $("tab-" + t).classList.toggle("hidden", t !== name));
}
document.querySelectorAll(".tab").forEach((t) => t.onclick = () => switchTab(t.dataset.tab));

/* ============================ Export ============================ */
function download(name, text, type = "text/plain") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
async function withResult(fn) {
  const m = await api(`/api/meetings/${currentMeetingId}`);
  fn(m, m.result || {});
}
$("exportMd").onclick = () => withResult((m, r) => download(
  slug(m.title) + ".md", (r.summary && r.summary.minutes_markdown) || "尚無會議記錄。", "text/markdown"));
$("exportTxt").onclick = () => withResult((m, r) => {
  SPEAKER_NAMES = r.speaker_names || {};
  download(slug(m.title) + ".txt", (r.segments || []).map((s) =>
    `[${fmtTime(s.start)}] ${s.speaker ? spName(s.speaker) + ": " : ""}${displayText(s)}`).join("\n"));
});
$("copyBtn").onclick = () => withResult((m, r) => {
  const s = r.summary || {};
  const txt = [s.summary, "", "Highlights:", ...(s.highlights || []).map((h) => "• " + h)].join("\n");
  navigator.clipboard.writeText(txt).then(() => flash($("copyBtn"), "已複製！"));
});
$("exportDocx").onclick = () => {
  const a = document.createElement("a");
  a.href = `/api/meetings/${currentMeetingId}/minutes.docx`;
  a.click();
};
$("emailBtn").onclick = () => withResult((m, r) => {
  const s = r.summary || {};
  SPEAKER_NAMES = r.speaker_names || {};
  const L = [`主旨：${m.title} — 會議記錄`, "", new Date(m.created_at * 1000).toLocaleString(), ""];
  if (s.summary) L.push(s.summary, "");
  if ((s.highlights || []).length) L.push("重點：", ...s.highlights.map((h) => "• " + h), "");
  if ((s.decisions || []).length) L.push("決議：", ...s.decisions.map((d) => "• " + d), "");
  if ((s.action_items || []).length) L.push("行動項目：",
    ...s.action_items.map((a) => `• ${a.task}${a.owner ? "（" + a.owner + "）" : ""}${a.due ? " — " + a.due : ""}`), "");
  navigator.clipboard.writeText(L.join("\n")).then(() => flash($("emailBtn"), "✓ 已複製"));
});
$("cleanupBtn").onclick = async () => {
  const prov = firstAiProvider();
  if (!prov) { alert("AI 校對需要 Claude／GPT／Gemini 金鑰（Gemini 有免費額度），請在 .env 設定。"); return; }
  const btn = $("cleanupBtn"), orig = btn.textContent;
  btn.disabled = true; btn.textContent = "AI 校對中…";
  try {
    await api(`/api/meetings/${currentMeetingId}/cleanup?provider=${prov}`, { method: "POST" });
    const m = await api(`/api/meetings/${currentMeetingId}`);
    transcriptView = "clean";
    renderMeeting(m); switchTab("transcript");
  } catch (e) {
    alert("AI 校對失敗：" + (e.detail || e.message || JSON.stringify(e)));
  } finally {
    btn.disabled = false; btn.textContent = orig;
  }
};
$("retransBtn").onclick = async () => {
  if (!confirm("以國語（繁體中文）重新轉錄這場會議？會覆蓋現有逐字稿與摘要。")) return;
  try {
    await api(`/api/meetings/${currentMeetingId}/retranscribe?language=zh`, { method: "POST" });
    show("procView"); pollStatus(currentMeetingId); loadList();
  } catch (e) {
    alert("重新轉錄失敗：" + (e.detail || e.message || JSON.stringify(e)));
  }
};
$("deleteBtn").onclick = async () => {
  if (!confirm("確定要永久刪除這場會議及其音訊嗎？")) return;
  await api(`/api/meetings/${currentMeetingId}`, { method: "DELETE" });
  currentMeetingId = null; show("newView"); loadList();
};
function flash(btn, txt) { const o = btn.textContent; btn.textContent = txt; setTimeout(() => btn.textContent = o, 1200); }
const slug = (s) => (s || "meeting").replace(/[^\w一-鿿]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "meeting";

/* ============================ Minimal Markdown ============================ */
function mdToHtml(md) {
  const lines = md.replace(/\r/g, "").split("\n");
  let html = "", i = 0;
  const inline = (t) => esc(t)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*$/.test(line)) { i++; continue; }
    let m;
    if ((m = line.match(/^(#{1,6})\s+(.*)/))) { html += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`; i++; continue; }
    if (line.includes("|") && lines[i + 1] && /^\s*\|?[-:\s|]+\|?\s*$/.test(lines[i + 1])) {
      const cells = (r) => r.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(line); i += 2; let rows = "";
      while (i < lines.length && lines[i].includes("|")) { rows += `<tr>${cells(lines[i]).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`; i++; }
      html += `<table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>`;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      let items = "";
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { items += `<li>${inline(lines[i].replace(/^\s*[-*]\s+/, ""))}</li>`; i++; }
      html += `<ul>${items}</ul>`; continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      let items = "";
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { items += `<li>${inline(lines[i].replace(/^\s*\d+\.\s+/, ""))}</li>`; i++; }
      html += `<ol>${items}</ol>`; continue;
    }
    html += `<p>${inline(line)}</p>`; i++;
  }
  return html;
}

/* ============================ Wiring ============================ */
$("recBtn").onclick = startRecording;
$("stopBtn").onclick = stopRecording;
$("newBtn").onclick = () => { currentMeetingId = null; show("newView"); loadList(); };
$("fileInput").onchange = (e) => { if (e.target.files[0]) { $("fileName").textContent = e.target.files[0].name; uploadAudio(e.target.files[0], e.target.files[0].name); } };
const dz = $("dropzone");
["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
dz.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) { $("fileName").textContent = f.name; uploadAudio(f, f.name); } });

/* ---- Global search across all meetings ---- */
let searchTimer = null;
function highlight(text, q) {
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return esc(text);
  return esc(text.slice(0, i)) + "<mark>" + esc(text.slice(i, i + q.length)) + "</mark>" + esc(text.slice(i + q.length));
}
$("globalSearch").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if (!q) { loadList(); return; }
  searchTimer = setTimeout(async () => {
    try { renderSearchResults((await api(`/api/search?q=${encodeURIComponent(q)}`)).results || [], q); }
    catch (err) { /* ignore */ }
  }, 300);
});
function renderSearchResults(results, q) {
  const el = $("meetingList");
  if (!results.length) { el.innerHTML = `<p class="muted small" style="padding:8px">找不到「${esc(q)}」。</p>`; return; }
  el.innerHTML = results.map((m) => `
    <div class="item sresult" data-id="${m.id}" data-t="${m.start}">
      <div class="t" style="white-space:normal">${highlight(m.text, q)}</div>
      <div class="m">${esc(m.title)} · ${fmtTime(m.start)}${m.speaker ? " · " + esc(m.speaker) : ""}</div>
    </div>`).join("");
  el.querySelectorAll(".sresult").forEach((n) => n.onclick = async () => {
    await openMeeting(n.dataset.id); switchTab("transcript");
    const p = $("player"); if (p) { p.currentTime = Number(n.dataset.t); p.play(); }
  });
}

/* ---- Mic test ---- */
$("micTest").onclick = async () => {
  const btn = $("micTest"), res = $("micTestResult");
  btn.disabled = true; res.textContent = " 測試中…請正常說話";
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const an = ctx.createAnalyser(); an.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Uint8Array(an.fftSize);
    let peak = 0, sum = 0, n = 0;
    const t0 = Date.now();
    await new Promise((resolve) => {
      const tick = () => {
        an.getByteTimeDomainData(buf);
        let m = 0;
        for (const v of buf) { const d = Math.abs(v - 128) / 128; if (d > m) m = d; sum += d; n++; }
        if (m > peak) peak = m;
        res.textContent = " 音量 " + "▮".repeat(Math.min(20, Math.round(m * 25)));
        Date.now() - t0 < 5000 ? requestAnimationFrame(tick) : resolve();
      };
      tick();
    });
    stream.getTracks().forEach((t) => t.stop()); ctx.close();
    const avg = sum / Math.max(1, n);
    res.textContent = peak < 0.03 ? " ⚠ 幾乎沒有聲音 — 檢查麥克風權限與音量。"
      : (peak < 0.08 || avg < 0.01) ? " ⚠ 音量偏小 — 請靠近麥克風或調高輸入音量。"
      : " ✓ 麥克風良好，可以開始錄音。";
  } catch (e) { res.textContent = " 無法存取麥克風：" + e.message; }
  btn.disabled = false;
};

/* ---- Keyboard shortcuts (during playback review) ---- */
document.addEventListener("keydown", (e) => {
  const el = document.activeElement;
  if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
  if ($("meetingView").classList.contains("hidden")) return;
  const p = $("player"); if (!p || !p.src) return;
  if (e.code === "Space") { e.preventDefault(); p.paused ? p.play() : p.pause(); }
  else if (e.code === "ArrowLeft") { e.preventDefault(); p.currentTime = Math.max(0, p.currentTime - 5); }
  else if (e.code === "ArrowRight") { e.preventDefault(); p.currentTime = Math.min(p.duration || 1e9, p.currentTime + 5); }
});

/* ---- Glossary (persistent vocabulary) ---- */
$("saveGlossary").onclick = async () => {
  try {
    await api("/api/glossary", { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ terms: $("optVocab").value.trim() }) });
    flash($("saveGlossary"), "✓ 已儲存");
  } catch (e) { alert("儲存失敗：" + (e.detail || e.message)); }
};
async function loadGlossary() {
  try {
    const g = await api("/api/glossary");
    if (g.terms && !$("optVocab").value.trim()) $("optVocab").value = g.terms;
  } catch (e) { /* ignore */ }
}

/* ---- Settings: confidential mode + retention ---- */
async function loadSettings() {
  try {
    const st = await api("/api/settings");
    $("confidential").checked = !!st.confidential_mode;
    $("retention").value = String(st.retention_days || 0);
    $("audioEnhance").checked = st.audio_enhance !== false;
  } catch (e) { /* ignore */ }
}
$("audioEnhance").onchange = async () => {
  await api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio_enhance: $("audioEnhance").checked }) });
};
$("confidential").onchange = async () => {
  await api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confidential_mode: $("confidential").checked }) });
  await loadCaps();   // re-evaluate which engines/AI are allowed
};
$("retention").onchange = async () => {
  await api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ retention_days: Number($("retention").value) }) });
};

(async function init() {
  await loadCaps();
  await loadGlossary();
  await loadSettings();
  await loadList();
  show("newView");
})();
