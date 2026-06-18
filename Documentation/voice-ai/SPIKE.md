# Phase-0 De-risk Spike — Voice Receive Layer (Go / No-Go)

> Branch: `voice-controlled-ai-bot`. Status: **GO (conditional)** — receive layer
> isolated behind a swappable interface; all offline-validatable behaviour is
> validated. One residual risk (live per-user capture on a DAVE channel) is
> explicitly deferred to a live smoke test.

## 1. What this spike is

Real-time **Discord voice receive** is the single fragile component of the
voice-controlled AI platform. This spike does **not** stand up a live voice
connection (no bot token / VC in this environment). Instead it:

1. Pins the receive surface behind one stable interface (`VoiceReceiver`) so the
   fragile backend can be swapped without touching anything downstream.
2. Validates everything that does **not** require a live capture — the DSP
   conversion, the energy VAD, the interface contract, and the
   backend-unavailable failure mode — with deterministic offline unit tests.
3. Documents the exact remediation + checklist needed to run the one remaining
   live test when a token + VC are available.

Files owned by this spike (all under `discord_bot/voice/`, plus tests + this doc):

| File | Lines | Purpose |
|---|---:|---|
| `discord_bot/voice/receive.py` | 447 | `VoiceReceiver` contract + 3 backends + `AudioChunk` + error |
| `discord_bot/voice/audio_utils.py` | 114 | pure DSP: downmix / resample / `to_stt_format` |
| `discord_bot/voice/vad.py` | 119 | energy-based VAD (`EnergyVAD`) |
| `tests/test_voice_receive.py` | 99 | offline tests for the receive abstraction |
| `tests/test_voice_audio.py` | 144 | offline tests for DSP + VAD |
| `Documentation/voice-ai/SPIKE.md` | this file | go/no-go writeup |

## 2. Receive-layer decision

**Default backend: discord.py + `discord-ext-voice-recv`, pinned `discord.py <= 2.6.4`, behind the `VoiceReceiver` abstraction.**

Rationale:
- Voice **receive** is not in discord.py mainline. `discord-ext-voice-recv` is the
  lowest-migration option because it keeps discord.py (and therefore the entire
  existing DKP cog/command codebase) unchanged.
- The extension is **alpha, unmaintained since ~June 2025, and currently broken**
  against discord.py 2.7.1 under Discord's **DAVE E2EE** (voice-recv issue #53).
- **This environment has discord.py 2.7.1 — i.e. the broken regime.** To capture
  live audio with the extension you must pin **`discord.py<=2.6.4`** alongside it.
  Nothing else in this spike depends on the pin; only live capture does.

**Escape hatch: Pycord 2.8.0 Sinks API.** Robust and maintained, but adopting it
is a **full library switch** (Pycord and discord.py cannot coexist in one
process) and its model is **record-then-callback** — no live per-chunk stream and
**no real-time speaking events**. The interface here is deliberately built to host
that backend too (`PycordSinkAdapter` stub) so the switch, if ever needed, is a
backend swap rather than a downstream rewrite.

Because both backends sit behind `VoiceReceiver`, the STT → VAD → intent →
dispatch pipeline is identical regardless of which one is live, and the fragile
choice is contained to a single file.

## 3. The interface contract (`VoiceReceiver`)

```
AudioChunk(user_id: int, pcm: bytes, sample_rate=48000, channels=2, timestamp: float)
```
One contiguous block of PCM attributed to a single speaker. Discord delivers
**48 kHz / 16-bit signed LE / stereo** per user.

`VoiceReceiver` (ABC) lifecycle:
- `await start(voice_channel)` — attach + begin capture. Raises
  `VoiceReceiveUnavailable` if the backend is unusable here.
- consume per-user `AudioChunk`s via **`async for chunk in receiver`** (required)
  and/or an `add_audio_callback(cb)` convenience.
- `on_speaking_start(cb)` / `on_speaking_stop(cb)` — hooks fired (best-effort) on
  Discord speaking transitions; drive push-to-talk gating + utterance
  segmentation. Sync **and** async callbacks supported. Backends that cannot
  produce real speaking events must document it and fall back to energy VAD.
- `await stop()` — stop capture, disconnect, end the async iterator.

Concrete backends:
- **`VoiceRecvAdapter`** — thin adapter over `discord-ext-voice-recv`. The
  extension is **lazy-imported inside `start()`**; if absent/incompatible,
  `start()` raises `VoiceReceiveUnavailable` with install + dpy-pin guidance.
  Maps the extension's sink `write()` and speaking events onto the contract,
  marshalling off-loop sink callbacks onto the event loop via an `asyncio.Queue`.
- **`PycordSinkAdapter`** — escape-hatch **stub**; every operational method raises
  `NotImplementedError` documenting the record-then-callback model.
- **`NullReceiver`** — no-network fake replaying a provided `AudioChunk` list and
  firing speaking hooks; used by tests and offline smoke.

`VoiceReceiveUnavailable(Exception)` — backend cannot be started here.

**Import-time guarantee:** `receive.py` imports nothing from `discord` or the
extension at module scope; the package imports clean with neither installed.

## 4. Integration point / data flow

The receive layer feeds the **already-built** core (`intent.py` + `dispatch.py`):

```
Discord VC (per user, 48kHz/16-bit/stereo)
        │
        ▼
  VoiceReceiver.start() ──► AudioChunk(user_id, pcm, 48000, 2)   [receive.py]
        │  (on_speaking_start/stop hooks gate PTT)
        ▼
  audio_utils.to_stt_format(chunk, 16000)  ──► mono 16kHz 16-bit PCM
        │     (downmix_stereo_to_mono → resample)
        ▼
  vad.EnergyVAD.segment(frames)  ──► [utterance_pcm, ...]
        │     (silero-vad swaps in behind same interface in prod)
        ▼
  STT (Deepgram Nova-3 / faster-whisper)  ──► transcript text
        │
        ▼
  intent.IntentParser.parse(transcript)  ──► IntentResult(command, args)   [intent.py — built]
        │
        ▼
  dispatch.Dispatcher.dispatch(...)  ──► validate + permission + confirm + handler   [dispatch.py — built]
```

`to_stt_format` does downmix-**before**-resample on purpose: it halves the sample
count before the more expensive rate conversion and avoids resampling a channel
about to be discarded.

## 5. Validated HERE vs. REQUIRES a live test (honest boundary)

**Validated offline in this spike (no Discord, no network):**
- The `VoiceReceiver` contract and that all three backends conform to it.
- `NullReceiver` replays chunks in order, fires `audio` callbacks, and fires
  `on_speaking_start` / `on_speaking_stop` correctly across speaker transitions
  (and stays silent when disabled).
- `VoiceRecvAdapter.start()` raises `VoiceReceiveUnavailable` (extension absent
  here) with install + `2.6.4` pin guidance in the message.
- `PycordSinkAdapter` raises `NotImplementedError` on `start()` and `__anext__()`.
- DSP: `downmix_stereo_to_mono` halves length and averages L/R; `resample`
  changes length by the rate ratio (and is a no-op when rates match);
  `to_stt_format` yields mono 16 kHz and rejects bad channel counts.
- `EnergyVAD`: silence → not speech, loud → speech, empty → not speech;
  `segment` groups one utterance, splits on a long gap, absorbs a short interior
  gap, and returns empty on pure silence.
- Import-cleanliness / network-freedom of the package.

**Requires a live test (NOT exercised here):**
- Actual per-user PCM **capture** from `discord-ext-voice-recv` on a **live DAVE
  channel** — this is the one residual risk. It needs a bot token, a real VC with
  speakers, the extension installed, and **`discord.py<=2.6.4`** pinned.
- Real `voice_member_speaking_start/stop` event delivery and the off-loop
  sink→queue marshalling under live load.
- End-to-end latency of capture → STT → intent → dispatch.

The live-capture wiring in `VoiceRecvAdapter.start()/stop()/__anext__()` is
written and documents the intended mapping, but is marked `# pragma: no cover`
because it cannot run without a live VC.

## 6. How to run the live smoke test (when token + VC are available)

1. Create a fresh venv pinned to the compatible discord.py:
   ```
   pip install "discord.py<=2.6.4" discord-ext-voice-recv
   ```
   (Confirm `discord-ext-voice-recv` imports: `python -c "from discord.ext import voice_recv"`.)
2. Provide a bot token with the **Voice States** + **message content** intents,
   and a guild VC with at least one human speaker.
3. Smoke script:
   ```python
   from discord_bot.voice.receive import VoiceRecvAdapter
   from discord_bot.voice.audio_utils import to_stt_format
   recv = VoiceRecvAdapter()
   recv.on_speaking_start(lambda uid: print("start", uid))
   recv.on_speaking_stop(lambda uid: print("stop", uid))
   await recv.start(voice_channel)        # raises VoiceReceiveUnavailable if misconfigured
   async for chunk in recv:               # speak in the VC
       pcm16k = to_stt_format(chunk)      # mono 16kHz, STT-ready
       print(chunk.user_id, len(pcm16k))
   # ... await recv.stop() to end
   ```
4. **Pass criteria:** per-user `AudioChunk`s arrive while speaking; `to_stt_format`
   yields non-empty mono 16 kHz PCM; speaking hooks fire on talk/stop; `stop()`
   cleanly ends the iterator and disconnects.
5. **If it fails under DAVE (issue #53):** confirm the `<=2.6.4` pin took effect;
   if still broken, switch to the **Pycord escape hatch** — implement
   `PycordSinkAdapter` against Pycord 2.8.0 Sinks (record-then-callback; lose live
   speaking events; rely on `EnergyVAD`/silero for segmentation). No downstream
   code changes.

## 7. Production notes

- **`audioop`** (used by `audio_utils` + `vad`) was **removed from the stdlib in
  Python 3.13**. This spike runs on **Python 3.12** where it is present (emits a
  `DeprecationWarning`). For 3.13+, install the drop-in **`audioop-lts`** backport
  or replace the helpers with a numpy path — the functions are isolated so the
  swap is local.
- **VAD:** `EnergyVAD` is the spike default. Production swaps in **silero-vad**
  (robust to noise/music) behind the **same** `is_speech` / `segment` interface;
  `webrtcvad` is a lighter alternative.
- Do **not** make `discord-ext-voice-recv` or Pycord hard dependencies — both stay
  lazy/optional so the package imports clean and the core platform never requires
  the fragile audio stack to be installed.

## 8. Verdict

**GO** for the receive layer as a swappable interface. The one fragile component
is fully isolated; the entire offline-validatable surface (interface + DSP + VAD +
backend-unavailable behaviour) passes deterministic tests. The only thing this
spike cannot prove without hardware/credentials — live per-user capture on a DAVE
channel — is explicitly scoped to the §6 live smoke test, with a fully-specified
remediation (pin `discord.py<=2.6.4`) and a fallback (Pycord escape hatch) if it
fails.
```
.\.venv\Scripts\python.exe -m pytest tests/test_voice_receive.py tests/test_voice_audio.py -q
# 19 passed (offline, no network)
```
