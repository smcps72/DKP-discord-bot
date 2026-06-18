# Voice-Controlled AI Platform — Refined Spec & Build Plan

> Produced by the CT6 (architect-team) pipeline intake/design phase, driven inline.
> Branch: `voice-controlled-ai-bot`. Status: **awaiting build-scope approval.**

## 1. Product

A **voice-controlled AI Discord bot platform**: an LLM turns a user's natural-language input
(spoken in a voice channel, or typed) into a **validated, permission-checked command** that the bot
executes. First host is the DKP bot, but the command layer is **extensible/programmable** so any
Discord app can register its own commands and outcomes.

### In scope (the 📈 ideas)
1. **Core platform** — input → (STT) → LLM intent → validate → execute command → reply.
2. **Programmable command interface** — third-party apps register commands (name, description, schema, handler).
3. **Push-to-talk** — opt-in toggle (cuts STT/LLM cost + protects privacy).
4. **Tiered plans** — free (text-only) vs paid (voice + TTS personas); usage warnings before limits.
5. **Voice-controlled guild bank** — remove items after auctions by voice (first concrete DKP use case).

### Deferred (🔄 — legally flagged in brainstorm) / out
- LLM moderation, sentiment analysis (GDPR / EU AI Act / ToS concerns) → not in this program.
- JSON product template → dropped by user.
- Character personas → ride along with the paid TTS tier (Phase 5), with content guardrails.

## 2. Recommended stack (from feasibility research)
| Layer | Default | Fallback / note |
|---|---|---|
| Discord lib | **discord.py** (current) + `discord-ext-voice-recv`, pinned **≤ 2.6.4** | Pycord 2.8.0 as escape hatch behind a receive abstraction |
| Utterance gate | toggle-button PTT + `on_voice_member_speaking_start/stop` + **silero-VAD** | webrtcvad |
| STT | **Deepgram Nova-3** streaming (~$0.005/min) | **faster-whisper** local ($0) |
| Intent | **Claude tool-use** (`claude-opus-4-8` default / `claude-haiku-4-5` hot path), one *strict* closed-schema tool per command, `tool_choice: any` | OpenAI adapter, swappable |
| Safety | server-side re-validation (existence/range/permission) + **confirm-on-destructive** | — |
| TTS (paid) | **ElevenLabs Flash v2.5** (~75 ms) via `FFmpegPCMAudio(pipe=True)` | Kokoro-82M local |
| Tier metering | **voice-minutes** (TTS ≈ 85–90% of voice cost); warn 75%, cap→text at 100% | — |

**Single biggest risk:** the audio-receive shim (alpha, currently broken on latest discord.py under DAVE).
Everything downstream is solid. → **De-risk by decoupling audio from the core (build text-first), behind a swappable receive interface.**

## 3. Architecture (reuse-first)
New package `discord_bot/voice/`:
- `registry.py` — **the extensibility seam.** A `CommandRegistry` of `VoiceCommand{name, description, json_schema, handler, destructive, permission}`. DKP/bank actions register here; third-party apps register here later. This is the same surface whether input is typed or spoken.
- `intent.py` — LLM adapter: builds one strict tool per registered command, forces a single call, returns `(command, args)`. Provider-agnostic (Claude default).
- `dispatch.py` — validate args server-side, check permission, run destructive-confirm if needed, call the handler.
- `handlers/` — thin handlers that call **existing** `bot.db.*` methods (`modify_user_dkp`, `guild_bank_deposit/withdraw`, `guild_bank_find_by_name`, etc.) + existing permission helpers + embed builders. **No business-logic duplication.**
- `receive.py` (later) — `VoiceReceiver` interface + `voice-recv` adapter (Pycord adapter swappable). Feeds transcripts into the *same* intent→dispatch path.
- `stt.py`, `tts.py`, `vad.py` (later) — adapters behind interfaces.
- Settings: new `guilds` columns via the existing migration system (`voice_enabled`, `voice_tier`, `voice_channel_id`, `voice_minutes_used`, …).

## 4. Phased plan
| Phase | Deliverable | Risk |
|---|---|---|
| **0. De-risk spike** | `VoiceReceiver` interface + voice-recv adapter; prove per-user PCM capture on a live channel; confirm dpy pin. Go/no-go on the receive layer. | isolates the one fragile component |
| **1. Core platform (text-first)** | `registry` + `intent` + `dispatch` + handlers; a `/ai <natural language>` command that maps text → validated DKP command → executes. Full extensible core, no audio. Tests. | low — pure logic |
| **2. Guild-bank voice use case** | Register bank deposit/withdraw as voice commands; **destructive-confirm** button flow; reuse fuzzy-match. | low |
| **3. Push-to-talk + audio** | Wire `receive.py` + `vad` + `stt` into the Phase-1 path; toggle-button control panel; `/voice start\|stop`. | medium — depends on Phase 0 |
| **4. Tiering + metering** | `voice_tier` column; voice-minute meter; 75%/100% warnings; extend `licensing_server` to return tier/entitlements; free=text / paid=voice gate. | low |
| **5. TTS + personas (paid)** | ElevenLabs adapter + FFmpeg playback; persona setting + guardrails. | low |
| **6. Programmable 3rd-party interface** | Public registry manifest so external apps load their own commands. | medium — API design |

## 5. Recommended build for THIS run
**Phases 0 → 2** = the de-risk spike + the full extensible core + the first real (guild-bank) use case,
built **text-first** so value lands immediately and the fragile audio shim is validated in parallel without
blocking. Phases 3–6 follow once the core is proven.
