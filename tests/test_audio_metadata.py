"""Tests for ragling.audio_metadata module."""

import wave
from pathlib import Path

import pytest

from ragling.audio_metadata import extract_audio_metadata


@pytest.fixture()
def wav_file(tmp_path: Path) -> Path:
    """Create a minimal WAV file (0.1 seconds of silence)."""
    path = tmp_path / "test.wav"
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 1600)  # 0.1s silence
    return path


class TestExtractAudioMetadata:
    def test_returns_dict(self, wav_file: Path) -> None:
        result = extract_audio_metadata(wav_file)
        assert isinstance(result, dict)

    def test_extracts_duration(self, wav_file: Path) -> None:
        result = extract_audio_metadata(wav_file)
        assert "duration_seconds" in result
        assert result["duration_seconds"] == pytest.approx(0.1, abs=0.05)

    def test_extracts_sample_rate(self, wav_file: Path) -> None:
        result = extract_audio_metadata(wav_file)
        assert result.get("sample_rate") == 16000

    def test_extracts_channels(self, wav_file: Path) -> None:
        result = extract_audio_metadata(wav_file)
        assert result.get("channels") == 1

    def test_returns_empty_dict_for_nonexistent_file(self, tmp_path: Path) -> None:
        result = extract_audio_metadata(tmp_path / "nonexistent.mp3")
        assert result == {}

    def test_returns_empty_dict_for_non_audio_file(self, tmp_path: Path) -> None:
        text_file = tmp_path / "readme.txt"
        text_file.write_text("not audio")
        result = extract_audio_metadata(text_file)
        assert result == {}


class TestExtractChapters:
    def test_returns_no_chapters_key_for_wav(self, wav_file: Path) -> None:
        """WAV files have no chapters — key should be absent."""
        result = extract_audio_metadata(wav_file)
        assert "chapters" not in result
