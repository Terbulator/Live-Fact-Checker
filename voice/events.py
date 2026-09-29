from typing import TypedDict


class TranscriptEvent(TypedDict):
    type: str
    sessionId: str
    speaker: str
    text: str
    timestamp: float
    isFinal: bool


def create_transcript_event(
    session_id: str,
    speaker: str,
    text: str,
    timestamp: float,
    is_final: bool,
) -> TranscriptEvent:
    """
    Convert an AssemblyAI transcript turn into
    the team's shared Transcript Event contract.
    """

    return {
        "type": "transcript",
        "sessionId": session_id,
        "speaker": speaker,
        "text": text.strip(),
        "timestamp": float(timestamp),
        "isFinal": is_final,
    }