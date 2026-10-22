"use strict";
// The device face: Koneho as a fixed grid of square pixels (48x58). The grid
// never moves and nothing is transformed -- animation is repainting cell
// colors from hand-authored frames (window.PIXEL_SPRITE, built by
// tools/sprite/build_sprite.py). She breathes, blinks, thinks, listens,
// speaks (mouth frames follow the real audio level), hops when a message
// arrives, and dozes off when idle. Also: TTS playback, WAV mic recording,
// image frame.

const $ = (id) => document.getElementById(id);
const dot = $("dot"), title = $("title"), linkState = $("link-state");
const koneho = $("koneho"), frame = $("frame"), img = $("stage-image");
const statusEl = $("status"), bubble = $("bubble"), replyEl = $("reply"), wave = $("wave");
const player = $("player"), soundHint = $("sound-hint");
const volumeSlider = $("volume");
const gridEl = $("pixel-grid");

const THINKING = ["thinking", "working", "researching", "planning", "processing",
                  "generating", "executing", "listening"];
let lastAudioId = null;
let pendingAudioUrl = null;
let volume = 0.8;
let lastReply = "";
let lastActivity = Date.now();
let typeTimer = null;
let speechLevel = 0;

// -- pixel player --------------------------------------------------------------

const SPRITE = window.PIXEL_SPRITE;
const cells = [];
let currentCells = null;   // palette index per cell, as currently painted

(function buildGrid() {
  const frag = document.createDocumentFragment();
  for (let i = 0; i < SPRITE.width * SPRITE.height; i++) {
    const c = document.createElement("i");
    frag.appendChild(c);
    cells.push(c);
  }
  gridEl.appendChild(frag);
})();

function decodeRow(row) {
  const out = new Array(row.length);
  for (let i = 0; i < row.length; i++) {
    const code = row.charCodeAt(i);
    out[i] = code <= 57 ? code - 48 : code - 87;   // '0'-'9' -> 0-9, 'a'-'f' -> 10-15
  }
  return out;
}

function showFrame(name) {
  const rows = SPRITE.frames[name];
  if (!rows) return;
  for (let y = 0; y < SPRITE.height; y++) {
    const row = decodeRow(rows[y]);
    const base = y * SPRITE.width;
    for (let x = 0; x < SPRITE.width; x++) {
      const idx = row[x];
      const pos = base + x;
      if (currentCells && currentCells[pos] === idx) continue;
      cells[pos].style.backgroundColor = idx === 0 ? "transparent" : SPRITE.palette[idx];
    }
  }
  currentCells = currentCells || new Array(SPRITE.width * SPRITE.height).fill(-1);
  for (let y = 0; y < SPRITE.height; y++) {
    const row = decodeRow(rows[y]);
    for (let x = 0; x < SPRITE.width; x++) currentCells[y * SPRITE.width + x] = row[x];
  }
}

// The player: a mode + a one-shot overlay (hop). Frame changes are driven by
// per-mode timers; a mode switch takes effect immediately (interruptible,
// never a restarted timeline).
let mode = "idle";           // idle | thinking | listening | speaking | sleep
let overlay = null;          // { frames: [[name, ms]...], i, until }
let playerTimer = null;
let idleFlip = false;
let sleepFlip = 0;

function schedule(fn, ms) {
  clearTimeout(playerTimer);
  playerTimer = setTimeout(fn, ms);
}

function paint(name, next, ms) {
  showFrame(name);
  schedule(next, ms);
}

function tick() {
  if (overlay) {
    const [name, ms] = overlay.frames[overlay.i];
    overlay.i++;
    if (overlay.i >= overlay.frames.length) overlay = null;
    paint(name, tick, ms);
    return;
  }
  if (mode === "thinking") {
    const seq = ["think1", "think2", "think3", "think2"];
    thinkStep = (thinkStep + 1) % seq.length;
    paint(seq[thinkStep], tick, thinkStep === 2 ? 520 : 300);
  } else if (mode === "speaking") {
    const f = speechLevel > 0.5 ? "talk2" : speechLevel > 0.13 ? "talk1" : "base";
    paint(f, tick, 90);
  } else if (mode === "sleep") {
    const seq = ["sleep0", "sleep1", "sleep2", "sleep1"];
    sleepFlip = (sleepFlip + 1) % seq.length;
    paint(seq[sleepFlip], tick, 620);
  } else if (mode === "listening") {
    paint("listen", tick, 700);
  } else {
    idleFlip = !idleFlip;
    paint(idleFlip ? "breathe" : "base", tick, 1350);
  }
}
let thinkStep = 0;

function setMode(next) {
  if (mode === next) return;
  mode = next;
  overlay = null;
  thinkStep = 0;
  clearTimeout(playerTimer);
  tick();
}

function playHop() {
  overlay = { frames: [["squash", 115], ["air", 105], ["fall", 85],
                       ["squash_deep", 105], ["base", 200]], i: 0 };
  clearTimeout(playerTimer);
  tick();
}

// blinking: irregular, only in calm modes
(function blinkLoop() {
  setTimeout(() => {
    if ((mode === "idle" || mode === "listening") && !overlay) {
      const back = mode === "listening" ? "listen" : (idleFlip ? "breathe" : "base");
      showFrame("blink");
      schedule(() => { showFrame(back); tick(); }, 120);
    }
    blinkLoop();
  }, 2400 + Math.random() * 3800);
})();

function currentMode() { return mode; }

// dozing off after 90 s without activity
setInterval(() => {
  if (Date.now() - lastActivity > 90000 && mode === "idle") setMode("sleep");
}, 4000);

function poke() {
  lastActivity = Date.now();
  if (mode === "sleep") setMode("idle");
}
addEventListener("pointerdown", poke);
addEventListener("keydown", poke);

showFrame("base");
tick();

// -- speech: the mouth follows the actual audio level --------------------------

let audioCtx = null, analyser = null, mouthRaf = 0, flapTimer = 0;

function ensureAnalyser() {
  if (analyser) return true;
  try {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = audioCtx.createMediaElementSource(player);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    src.connect(analyser);
    analyser.connect(audioCtx.destination);
    return true;
  } catch (_) {
    return false;
  }
}

function levelLoop() {
  const data = new Uint8Array(analyser.fftSize);
  let smooth = 0;
  const step = () => {
    if (player.paused || player.ended) { speechLevel = 0; return; }
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i += 4) { const v = (data[i] - 128) / 128; sum += v * v; }
    const rms = Math.sqrt(sum / (data.length / 4));
    smooth = Math.max(rms * 2.6, smooth * 0.72);
    speechLevel = smooth;
    mouthRaf = requestAnimationFrame(step);
  };
  step();
}

function startSpeaking() {
  setMode("speaking");
  wave.hidden = false;
  poke();
  if (ensureAnalyser()) {
    audioCtx.resume().catch(() => {});
    cancelAnimationFrame(mouthRaf);
    levelLoop();
  } else {
    // No analyser (autoplay policy): flap the level on a timer instead.
    let open = false;
    clearInterval(flapTimer);
    flapTimer = setInterval(() => { open = !open; speechLevel = open ? 0.8 : 0.1; }, 135);
  }
}

function stopSpeaking() {
  if (mode === "speaking") setMode("idle");
  wave.hidden = true;
  cancelAnimationFrame(mouthRaf);
  clearInterval(flapTimer);
  speechLevel = 0;
}

player.addEventListener("play", startSpeaking);
player.addEventListener("ended", stopSpeaking);
player.addEventListener("pause", stopSpeaking);

function playAudio(url) {
  player.src = url;
  player.volume = volume;
  player.play().catch(() => {
    pendingAudioUrl = url;
    soundHint.hidden = false;
  });
}
soundHint.addEventListener("click", () => {
  soundHint.hidden = true;
  if (pendingAudioUrl) playAudio(pendingAudioUrl);
});

// -- state from the gadget -----------------------------------------------------

function revealReply(text) {
  bubble.hidden = false;
  if (typeTimer) clearInterval(typeTimer);
  if (text.length <= 3) { replyEl.textContent = text; return; }
  replyEl.textContent = "";
  replyEl.classList.add("typing");
  const step = Math.max(1, Math.round(text.length / 42));
  let i = 0;
  typeTimer = setInterval(() => {
    i = Math.min(text.length, i + step);
    replyEl.textContent = text.slice(0, i);
    if (i >= text.length) {
      clearInterval(typeTimer);
      replyEl.classList.remove("typing");
    }
  }, 18);
}

function applyState(s) {
  dot.className = "dot " + (s.link_state || "boot");
  linkState.textContent = s.link_state || "";
  if (s.title) title.textContent = s.title;
  const thinking = THINKING.includes(s.status_text);
  statusEl.classList.toggle("thinking", thinking);
  statusEl.textContent = s.status_text || "";
  if (s.status_text) poke();
  if (thinking && mode !== "speaking" && mode !== "listening") setMode("thinking");
  if (!thinking && mode === "thinking") setMode("idle");

  if (s.reply_text !== lastReply) {
    lastReply = s.reply_text || "";
    if (lastReply) { revealReply(lastReply); if (mode !== "speaking") playHop(); }
    else bubble.hidden = true;
  }

  if (s.mode === "image") {
    frame.hidden = false;
    koneho.classList.add("behind");
    const want = "/img/current?v=" + s.image_version;
    if (img.getAttribute("src") !== want) img.src = want;
  } else {
    frame.hidden = true;
    koneho.classList.remove("behind");
  }

  if (typeof s.volume === "number") {
    volume = s.volume / 100;
    if (document.activeElement !== volumeSlider) volumeSlider.value = s.volume;
    player.volume = volume;
  }
  if (s.audio_id && s.audio_id !== lastAudioId) {
    lastAudioId = s.audio_id;
    playAudio("/audio/" + s.audio_id);
  }
}

$("frame-close").addEventListener("click", () => {
  fetch("/face", { method: "POST" }).catch(() => {});
});

function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(proto + "//" + location.host + "/ws");
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "state") applyState(msg);
    } catch (_) { /* ignore malformed pushes */ }
  };
  ws.onclose = () => setTimeout(connect, 1500);
  ws.onerror = () => ws.close();
}
connect();

volumeSlider.addEventListener("change", () => {
  fetch("/volume", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ volume: Number(volumeSlider.value) }),
  }).catch(() => {});
});

// -- Ask by text ---------------------------------------------------------------

const askForm = $("ask-form"), askInput = $("ask-input"), askButton = $("ask-button");
const mic = $("mic");

async function runTurn(url, options) {
  askButton.disabled = true;
  mic.disabled = true;
  statusEl.textContent = "thinking";
  statusEl.classList.add("thinking");
  setMode("thinking");
  try {
    const resp = await fetch(url, options);
    const result = await resp.json().catch(() => ({ ok: false, error: "bad reply" }));
    if (!result.ok) {
      statusEl.textContent = result.error || "something went wrong";
      statusEl.classList.remove("thinking");
      if (mode === "thinking") setMode("idle");
    }
    // The spoken clip + reply text arrive through the state push.
  } catch (err) {
    statusEl.textContent = "could not reach the gadget";
    statusEl.classList.remove("thinking");
    if (mode === "thinking") setMode("idle");
  } finally {
    askButton.disabled = false;
    mic.disabled = false;
  }
}

askForm.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const message = askInput.value.trim();
  if (!message) return;
  askInput.value = "";
  runTurn("/say", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
});

// -- Mic: record PCM in the browser, ship a 16 kHz mono WAV -------------------

let recording = null;

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
  writeStr(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, "WAVEfmt "); view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  writeStr(36, "data"); view.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([view], { type: "audio/wav" });
}

function downsample(chunks, fromRate, toRate) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const merged = new Float32Array(total);
  let off = 0;
  for (const c of chunks) { merged.set(c, off); off += c.length; }
  if (fromRate === toRate) return merged;
  const ratio = fromRate / toRate;
  const out = new Float32Array(Math.floor(total / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio), end = Math.floor((i + 1) * ratio);
    let sum = 0, n = 0;
    for (let j = start; j < end && j < total; j++) { sum += merged[j]; n++; }
    out[i] = n ? sum / n : 0;
  }
  return out;
}

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const ctx = new AudioContext();
  const source = ctx.createMediaStreamSource(stream);
  const processor = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  processor.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  source.connect(processor); processor.connect(ctx.destination);
  recording = { stream, ctx, processor, source, chunks, rate: ctx.sampleRate };
  mic.classList.add("recording");
  setMode("listening");
  statusEl.textContent = "listening";
}

async function stopRecording() {
  const rec = recording; recording = null;
  mic.classList.remove("recording");
  if (mode === "listening") setMode("idle");
  rec.processor.disconnect(); rec.source.disconnect();
  rec.stream.getTracks().forEach((t) => t.stop());
  await rec.ctx.close();
  const samples = downsample(rec.chunks, rec.rate, 16000);
  if (samples.length < 1600) { statusEl.textContent = ""; return; }   // accidental tap
  const wav = encodeWav(samples, 16000);
  runTurn("/voice", { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav });
}

mic.addEventListener("click", async () => {
  try {
    if (recording) await stopRecording();
    else await startRecording();
  } catch (err) {
    statusEl.textContent = "microphone unavailable";
    if (mode === "listening") setMode("idle");
  }
});
