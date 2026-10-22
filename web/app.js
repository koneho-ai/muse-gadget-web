"use strict";
// The device face: an animated Koneho driven by gadget state pushed over
// /ws. She blinks, twitches her ears, thinks, speaks (her mouth follows
// the real audio level), hops when a message arrives, and dozes off when
// idle. Also: TTS playback, WAV mic recording, image frame.

const $ = (id) => document.getElementById(id);
const dot = $("dot"), title = $("title"), linkState = $("link-state");
const koneho = $("koneho"), frame = $("frame"), img = $("stage-image");
const statusEl = $("status"), bubble = $("bubble"), replyEl = $("reply"), wave = $("wave");
const player = $("player"), soundHint = $("sound-hint");
const volumeSlider = $("volume");
const mouth = document.querySelector(".mouth-open ellipse");
const tongue = $("tongue");

const THINKING = ["thinking", "working", "researching", "planning", "processing",
                  "generating", "executing", "listening"];
let lastAudioId = null;
let pendingAudioUrl = null;
let volume = 0.8;
let lastReply = "";
let lastActivity = Date.now();
let typeTimer = null;

function poke() { lastActivity = Date.now(); koneho.classList.remove("sleepy"); }
addEventListener("pointerdown", poke);
addEventListener("keydown", poke);

// -- idle life: blinking, ear twitches, dozing -------------------------------

(function blinkLoop() {
  setTimeout(() => {
    koneho.classList.add("blink");
    setTimeout(() => koneho.classList.remove("blink"), 130);
    blinkLoop();
  }, 2200 + Math.random() * 3200);
})();

(function twitchLoop() {
  setTimeout(() => {
    const cls = Math.random() < 0.5 ? "twitch-left" : "twitch-right";
    koneho.classList.add(cls);
    setTimeout(() => koneho.classList.remove(cls), 520);
    twitchLoop();
  }, 6000 + Math.random() * 6000);
})();

setInterval(() => {
  if (Date.now() - lastActivity > 90000 && !koneho.classList.contains("speaking")) {
    koneho.classList.add("sleepy");
  }
}, 5000);

// -- speech: mouth follows the actual audio level ----------------------------

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

function setMouth(level) {
  const open = Math.max(0, Math.min(1, level));
  mouth.setAttribute("ry", (open * 10.5).toFixed(1));
  tongue.setAttribute("ry", (open * 5).toFixed(1));
}

function mouthLoop() {
  const data = new Uint8Array(analyser.fftSize);
  let smooth = 0;
  const step = () => {
    if (player.paused || player.ended) { setMouth(0); return; }
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i += 4) { const v = (data[i] - 128) / 128; sum += v * v; }
    const rms = Math.sqrt(sum / (data.length / 4));
    smooth = Math.max(rms * 2.6, smooth * 0.72);
    setMouth(smooth);
    mouthRaf = requestAnimationFrame(step);
  };
  step();
}

function startSpeaking() {
  koneho.classList.add("speaking");
  wave.hidden = false;
  poke();
  if (ensureAnalyser()) {
    audioCtx.resume().catch(() => {});
    cancelAnimationFrame(mouthRaf);
    mouthLoop();
  } else {
    // No analyser (autoplay policy): flap the mouth on a timer instead.
    let open = false;
    clearInterval(flapTimer);
    flapTimer = setInterval(() => { open = !open; setMouth(open ? 0.75 : 0.15); }, 135);
  }
}

function stopSpeaking() {
  koneho.classList.remove("speaking");
  wave.hidden = true;
  cancelAnimationFrame(mouthRaf);
  clearInterval(flapTimer);
  setMouth(0);
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

function hop() {
  koneho.classList.remove("happy");
  void koneho.offsetWidth;
  koneho.classList.add("happy");
  setTimeout(() => koneho.classList.remove("happy"), 1300);
}

function applyState(s) {
  dot.className = "dot " + (s.link_state || "boot");
  linkState.textContent = s.link_state || "";
  if (s.title) title.textContent = s.title;
  const thinking = THINKING.includes(s.status_text);
  koneho.classList.toggle("thinking", thinking);
  statusEl.classList.toggle("thinking", thinking);
  statusEl.textContent = s.status_text || "";
  if (s.status_text) poke();

  if (s.reply_text !== lastReply) {
    lastReply = s.reply_text || "";
    if (lastReply) { revealReply(lastReply); hop(); }
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
  koneho.classList.add("thinking");
  try {
    const resp = await fetch(url, options);
    const result = await resp.json().catch(() => ({ ok: false, error: "bad reply" }));
    if (!result.ok) {
      statusEl.textContent = result.error || "something went wrong";
      statusEl.classList.remove("thinking");
      koneho.classList.remove("thinking");
    }
    // The spoken clip + reply text arrive through the state push.
  } catch (err) {
    statusEl.textContent = "could not reach the gadget";
    statusEl.classList.remove("thinking");
    koneho.classList.remove("thinking");
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
  koneho.classList.add("listening");
  statusEl.textContent = "listening";
}

async function stopRecording() {
  const rec = recording; recording = null;
  mic.classList.remove("recording");
  koneho.classList.remove("listening");
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
    koneho.classList.remove("listening");
  }
});
