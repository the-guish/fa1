"""A checkpoint of this engine's: the Cursor chat that holds the conversation, and a mark of the
turn that ended on it. One string the caller keeps and never looks inside.

Cursor's CLI continues a chat from its end alone, so the chat is all the next turn needs. The
mark makes each turn's checkpoint its own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from robinauts.agent_engines.contract.domain import CheckpointNotFoundError

SEPARATOR = "#"


@dataclass(frozen=True, slots=True)
class Checkpoint:
    chat: str
    """The id of the Cursor chat: what ``--resume`` takes."""
    turn: str
    """A mark of the turn's own."""


def new(chat: str) -> Checkpoint:
    return Checkpoint(chat, uuid.uuid4().hex)


def encode(checkpoint: Checkpoint) -> str:
    return f"{checkpoint.chat}{SEPARATOR}{checkpoint.turn}"


def decode(text: str) -> Checkpoint:
    """``CheckpointNotFoundError`` for a string that is not one of this engine's."""
    chat, separator, turn = text.rpartition(SEPARATOR)
    if not separator or not chat.strip() or not turn or chat != chat.strip() or " " in chat:
        raise CheckpointNotFoundError(f"checkpoint {text!r} is not one of this engine's")
    return Checkpoint(chat, turn)
