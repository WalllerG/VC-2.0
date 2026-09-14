import datetime
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dotenv import load_dotenv

load_dotenv()

# Used when the user's Google Calendar timezone can't be read.
DEFAULT_TIMEZONE = "America/Toronto"


class ConfigError(RuntimeError):
    """The deployment is misconfigured — no amount of retrying will fix it."""


def api_key():
    """The Anthropic key, checked before httpx tries to put it in a header.

    A key with a stray non-ASCII character (easy to introduce by pasting from a
    document, or by the macOS accent picker while editing the field) fails deep
    inside httpx with an opaque UnicodeEncodeError and no mention of the key.
    """
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise ConfigError("ANTHROPIC_API_KEY is not set.")
    try:
        key.encode("ascii")
    except UnicodeEncodeError as exc:
        bad = key[exc.start]
        raise ConfigError(
            f"ANTHROPIC_API_KEY contains a non-ASCII character "
            f"{bad!r} (U+{ord(bad):04X}) at position {exc.start}. "
            f"Re-copy the key from the Anthropic console."
        ) from exc
    return key


def resolve_timezone(name):
    """Return (name, tzinfo) for a timezone, falling back if it isn't usable.

    Google can hand back a zone this machine doesn't know, and a missing tzdata
    makes even the default unusable, so this never raises.
    """
    for candidate in (name, DEFAULT_TIMEZONE):
        if not candidate:
            continue
        try:
            return candidate, ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return "UTC", datetime.timezone.utc
