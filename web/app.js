"use strict";
// The device face: renders gadget state pushed over /ws, plays TTS reply
// clips, and records WAV voice notes for the mic button.

const $ = (id) => document.getElementById(id);
const dot = $("dot"), title = $("title"), linkState = $("link-state");
const face = $("face"), img = $("stage-image");
const statusEl = $("status"), replyEl = $("reply");
const player = $("player"), soundHint = $("sound-hint");
const volumeSlider = $("volume");

let lastAudioId = null;
let pendingAudioUrl = null;
let volume = 0.8;

function playAudio(url) {
  player.src = url;
  player.volume = volume;
  player.play().catch(() => {
    pendingAudioUrl = url;
    soundHint.hidden = false;
  });
}
player.addEventListener("play", () => face.classList.add("speaking"));
player.addEventListener("ended", () => face.classList.remove("speaking"));
player.addEventListener("pause", () => face.classList.remove("speaking"));
soundHint.addEventListener("click", () => {
  soundHint.hidden = true;
  if (pendingAudioUrl) playAudio(pendingAudioUrl);
});

function applyState(s) {
  dot.className = "dot " + (s.link_state || "boot");
  linkState.textContent = s.link_state || "";
  if (s.title) title.textContent = s.title;
  const thinking = ["thinking", "working", "researching", "planning", "processing", "generating", "executing", "listening"].includes(s.status_text);
  face.classList.toggle("thinking", thinking);
  statusEl.textContent = s.status_text || "";
  replyEl.textContent = s.reply_text || "";
  if (s.mode === "image") {
    face.hidden = true;
    img.hidden = false;
    const want = "/img/current?v=" + s.image_version;
    if (img.getAttribute("src") !== want) img.src = want;
  } else {
    img.hidden = true;
    face.hidden = false;
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

async function runTurn(url, options) {
  askButton.disabled = true;
  mic.disabled = true;
  statusEl.textContent = "thinking";
  try {
    const resp = await fetch(url, options);
    const result = await resp.json().catch(() => ({ ok: false, error: "bad reply" }));
    if (!result.ok) statusEl.textContent = result.error || "something went wrong";
    // The spoken clip + reply text arrive through the state push.
  } catch (err) {
    statusEl.textContent = "could not reach the gadget";
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

const mic = $("mic");
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
}

async function stopRecording() {
  const rec = recording; recording = null;
  mic.classList.remove("recording");
  rec.processor.disconnect(); rec.source.disconnect();
  rec.stream.getTracks().forEach((t) => t.stop());
  await rec.ctx.close();
  const samples = downsample(rec.chunks, rec.rate, 16000);
  if (samples.length < 1600) return;   // accidental tap: <100 ms of audio
  const wav = encodeWav(samples, 16000);
  runTurn("/voice", { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav });
}

mic.addEventListener("click", async () => {
  try {
    if (recording) await stopRecording();
    else await startRecording();
  } catch (err) {
    statusEl.textContent = "microphone unavailable";
  }
});
