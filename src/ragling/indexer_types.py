"""Centralised indexer type constants."""

from enum import StrEnum


class IndexerType(StrEnum):
    PROJECT = "project"
    CODE = "code"
    OBSIDIAN = "obsidian"
    EMAIL = "email"
    CALIBRE = "calibre"
    RSS = "rss"
    PRUNE = "prune"
