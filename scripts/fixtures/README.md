# Benchmark Fixtures

Place test files here. See `docs/plans/2026-02-18-benchmark-tool-design.md` for the full fixture list.

## Required fixtures

Files must be freely distributable (public domain or generated).

- `pdf-1pg-text.pdf` — Single page, text only
- `pdf-10pg-mixed.pdf` — 10 pages with text, tables, and images
- `pdf-50pg-dense.pdf` — 50 pages, dense text
- `docx-5pg.docx` — 5-page Word document
- `pptx-10slides.pptx` — 10-slide presentation with images
- `audio-30s.mp3` — 30-second audio clip
- `audio-5min.mp3` — 5-minute audio clip
- `image-photo.jpg` — Photograph (~1-2 MB)
- `image-diagram.png` — Diagram/chart
- `epub-short.epub` — Short ebook (few chapters)
- `markdown-5pg.md` — Markdown with headings (included)
- `plaintext-10kb.txt` — Plain text (included)

## Git repos

Generated automatically by the benchmark tool on first run:
- `git-repo-small/` — ~10 files, few commits
- `git-repo-large/` — 100+ files, deeper history
