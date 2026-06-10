from __future__ import annotations


class DeepgramError(Exception):
    """Raised when the Deepgram STT connection or transcription fails."""


class ElevenLabsError(Exception):
    """Raised when ElevenLabs TTS synthesis fails."""


class TwilioError(Exception):
    """Raised when a Twilio REST API call fails."""


class ClaudeError(Exception):
    """Raised when the Anthropic Claude API call fails."""
