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
]
