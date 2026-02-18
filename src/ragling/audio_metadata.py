"""Audio/video container metadata extraction via mutagen.

Best-effort extraction — returns empty dict on any failure.
Requires the ``mutagen`` package (installed with ``asr`` or ``asr-mlx`` extras).
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def extract_audio_metadata(path: Path) -> dict[str, Any]:
    """Extract container metadata from an audio/video file.

    Uses mutagen to read tags (ID3, Vorbis comments, MP4 atoms, etc.)
    and stream info (duration, sample rate, channels, bitrate).

    Args:
        path: Path to the audio/video file.

    Returns:
        A dict of metadata fields. Empty dict if extraction fails
        or mutagen is not installed.
    """
    if not path.exists():
        return {}

    try:
        import mutagen
    except ImportError:
        logger.warning("mutagen not installed — skipping audio metadata extraction")
        return {}

    try:
        audio = mutagen.File(str(path))
    except Exception:
        logger.debug("mutagen could not open %s", path)
        return {}

    if audio is None:
        return {}

    metadata: dict[str, Any] = {}

    # Stream info (duration, sample rate, channels, bitrate)
    info = getattr(audio, "info", None)
    if info is not None:
        if hasattr(info, "length") and info.length:
            metadata["duration_seconds"] = round(info.length, 2)
        if hasattr(info, "sample_rate") and info.sample_rate:
            metadata["sample_rate"] = info.sample_rate
        if hasattr(info, "channels") and info.channels:
            metadata["channels"] = info.channels
        if hasattr(info, "bitrate") and info.bitrate:
            metadata["bitrate"] = info.bitrate

    # Tags — normalize across formats
    _extract_tags(audio, metadata)

    return metadata


def _extract_tags(audio: Any, metadata: dict[str, Any]) -> None:
    """Extract common tags from mutagen audio object.

    Handles ID3 (MP3), Vorbis comments (OGG/FLAC/Opus), MP4 atoms,
    and other mutagen-supported tag formats.

    Args:
        audio: A mutagen File object.
        metadata: Dict to populate with tag values.
    """
    tags = audio.tags
    if tags is None:
        return

    # Tag key mappings: (metadata_key, [possible_tag_keys])
    # ID3 uses TIT2/TPE1/TALB, Vorbis uses title/artist/album,
    # MP4 uses \xa9nam/\xa9ART/\xa9alb
    _TAG_MAP: list[tuple[str, list[str]]] = [
        ("title", ["TIT2", "title", "\xa9nam", "TITLE"]),
        ("artist", ["TPE1", "artist", "\xa9ART", "ARTIST"]),
        ("album", ["TALB", "album", "\xa9alb", "ALBUM"]),
        ("genre", ["TCON", "genre", "\xa9gen", "GENRE"]),
        ("date", ["TDRC", "date", "\xa9day", "DATE", "YEAR"]),
        ("track_number", ["TRCK", "tracknumber", "trkn", "TRACKNUMBER"]),
    ]

    for meta_key, tag_keys in _TAG_MAP:
        for tag_key in tag_keys:
            value = tags.get(tag_key)
            if value is not None:
                # mutagen returns list-like objects for most tags
                text = str(value[0]) if hasattr(value, "__getitem__") else str(value)
                if text:
                    metadata[meta_key] = text
                break
