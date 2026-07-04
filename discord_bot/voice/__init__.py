"""Voice-controlled AI command platform (text-first core).

Public surface for the extensible command platform. Import-time side-effect-free
and network-free — the Anthropic SDK is only imported lazily inside
``ClaudeIntentParser.parse``.
"""

from .registry import CommandRegistry, VoiceCommand, build_default_registry
from .intent import (
    IntentParser,
    IntentResult,
    ClaudeIntentParser,
    ScriptedIntentParser,
)
from .dispatch import Dispatcher, DispatchContext, DispatchResult
from .receive import (
    AudioChunk,
    VoiceReceiver,
    VoiceRecvAdapter,
    PycordSinkAdapter,
    NullReceiver,
    VoiceReceiveUnavailable,
    SpeakingHook,
)
from .audio_utils import downmix_stereo_to_mono, resample, to_stt_format
from .vad import EnergyVAD
from .tiering import (
    FREE,
    PAID,
    VALID_TIERS,
    VOICE_MINUTE_LIMITS,
    Entitlements,
    tier_from_license,
    voice_allowed,
    usage_state,
    load_entitlements,
    reset_if_new_period,
    voice_billing_enforced,
)
from .plugins import (
    ManifestError,
    RESERVED_COMMAND_NAMES,
    validate_command_manifest,
    build_command_from_manifest,
    register_manifest,
    discover_plugins,
)
from .stt import SttEngine, ScriptedStt, DeepgramStt, FasterWhisperStt, SttUnavailable
from .session import VoiceSession, VoiceSessionConfig
from .personas import (
    Persona,
    PERSONAS,
    DEFAULT_PERSONA_KEY,
    get_persona,
    list_personas,
    sanitize_for_speech,
    screen_text,
    apply_persona,
)
from .tts import TtsEngine, ScriptedTts, ElevenLabsTts, TtsUnavailable, speak

__all__ = [
    "CommandRegistry",
    "VoiceCommand",
    "build_default_registry",
    "IntentParser",
    "IntentResult",
    "ClaudeIntentParser",
    "ScriptedIntentParser",
    "Dispatcher",
    "DispatchContext",
    "DispatchResult",
    # audio-receive spike (offline-validated)
    "AudioChunk",
    "VoiceReceiver",
    "VoiceRecvAdapter",
    "PycordSinkAdapter",
    "NullReceiver",
    "VoiceReceiveUnavailable",
    "SpeakingHook",
    "downmix_stereo_to_mono",
    "resample",
    "to_stt_format",
    "EnergyVAD",
    # Phase 4 — tiering + metering
    "FREE",
    "PAID",
    "VALID_TIERS",
    "VOICE_MINUTE_LIMITS",
    "Entitlements",
    "tier_from_license",
    "voice_allowed",
    "usage_state",
    "load_entitlements",
    "reset_if_new_period",
    "voice_billing_enforced",
    # Phase 6 — programmable third-party command interface
    "ManifestError",
    "RESERVED_COMMAND_NAMES",
    "validate_command_manifest",
    "build_command_from_manifest",
    "register_manifest",
    "discover_plugins",
    # Phase 3 — push-to-talk + live audio
    "SttEngine",
    "ScriptedStt",
    "DeepgramStt",
    "FasterWhisperStt",
    "SttUnavailable",
    "VoiceSession",
    "VoiceSessionConfig",
    # Phase 5 — TTS + personas
    "Persona",
    "PERSONAS",
    "DEFAULT_PERSONA_KEY",
    "get_persona",
    "list_personas",
    "sanitize_for_speech",
    "screen_text",
    "apply_persona",
    "TtsEngine",
    "ScriptedTts",
    "ElevenLabsTts",
    "TtsUnavailable",
    "speak",
]
