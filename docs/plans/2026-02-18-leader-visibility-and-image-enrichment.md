# Leader Visibility + Image Enrichment

Two small, independent improvements bundled together.

## Part 1: Leader Role Visibility

### Problem

Each ragling group elects a leader process (via `fcntl.flock`). Leader status is only visible in logs. MCP clients and CLI users have no way to know whether a process is a leader or follower, or whether any leader is running for a group.

### Design

**MCP: Add `role` to `rag_list_collections` response**

```json
{
  "result": [...],
  "role": "leader",
  "indexing": { ... }
}
```

- Add `role_getter: Callable[[], str] | None` parameter to `create_server()`
- `_build_list_response()` includes `"role"` when getter is provided
- CLI `serve` passes `role_getter=lambda: "leader" if lock.is_leader else "follower"`

**CLI: Add leader detection to `ragling status`**

- Add `is_leader_running(config: Config) -> bool` helper to `leader.py`
- Attempts non-blocking `flock` on the group's lock file, releases immediately
- If `flock` succeeds: no leader running. If `BlockingIOError`: leader active.
- `ragling status` adds a "Leader" row: `active` or `none`

### Steps

1. **`leader.py`**: Add `is_leader_running()` function
   - Test: calling it with no lock held returns `False`
   - Test: calling it while a lock is held returns `True`

2. **`mcp_server.py`**: Add `role_getter` to `create_server()`
   - Thread through to `_build_list_response()`
   - Add `"role"` field to response when getter is provided
   - Test: `rag_list_collections` includes `"role": "leader"` when getter returns leader
   - Test: `rag_list_collections` omits `"role"` when no getter provided (backwards compat)

3. **`cli.py` serve**: Wire `lock.is_leader` into `create_server()`
   - Pass `role_getter=lambda: "leader" if lock.is_leader else "follower"`

4. **`cli.py` status**: Add leader row
   - Call `is_leader_running()` and display result
   - Test: status output includes "Leader" row

## Part 2: Standalone Image Enrichment

### Problem

Docling's picture description enrichment (`do_picture_description=True` with SmolVLM) only fires for images embedded in PDFs. Standalone image files (`.png`, `.jpg`, etc.) go through the image pipeline which doesn't run VLM enrichment. This is a [known Docling limitation](https://github.com/docling-project/docling/issues/2446) — standalone images are not enriched with descriptions.

Result: standalone images convert to empty text, produce zero chunks, and get silently skipped.

### Design

Work around the Docling limitation by generating descriptions ourselves when Docling returns empty content for image files. After converting an image via Docling, if the result has no text content:

1. Load the image
2. Run Docling's `DocumentFigureClassifier` to get the image class (chart, diagram, photo, logo, etc.)
3. Run SmolVLM to generate a natural language caption
4. Use the caption as the chunk's `.text` (vector-searchable), store the classification in `metadata["image_class"]`

This keeps everything local (SmolVLM runs on-device) and reuses the model ragling already downloads for PDF picture descriptions.

### Decisions

- **Classification + description**: Run both. Classification goes to `metadata["image_class"]` for filtering. Description becomes the chunk `.text` for vector/FTS search.
- **Model choice**: Start with SmolVLM (256M), already in use for PDF enrichment. Upgrade to Granite Vision (2B, ~6GB at fp16) only if caption quality proves insufficient. Avoids adding a second large model download.
- **Caching**: Lazy-load with `@lru_cache` — same pattern as `get_converter()`. Model loads on first image, stays cached for process lifetime. No new infrastructure needed.

### Steps

5. **Investigate SmolVLM direct usage**: Check how to call the picture description model directly outside the PDF pipeline. The model is already loaded by `get_converter()` — determine if we can reuse it or need to instantiate separately. Also check direct usage of `DocumentFigureClassifier`.

6. **Add `describe_image()` helper to `docling_convert.py`**:
   - Takes a `Path` to an image file
   - Runs `DocumentFigureClassifier` to get image class
   - Runs SmolVLM to generate a text caption
   - Returns `(description: str, image_class: str)`
   - Lazy-loaded with `@lru_cache` for both models
   - Test: calling with `kittens.jpg` returns non-empty description mentioning cats/kittens
   - Test: calling with a chart image returns a classification like "chart"

7. **Integrate into `convert_and_chunk()`**:
   - After Docling conversion, if source type is `"image"` and the DoclingDocument has no text content, call `describe_image()`
   - Build a DoclingDocument from the description and chunk it normally
   - Store `image_class` in chunk metadata
   - Test: converting a photo produces at least one chunk with descriptive text
   - Test: chunk metadata includes `image_class`

8. **Consider audio**: ~~Check if standalone audio files have the same empty-result problem.~~ **Done.** Audio requires `openai-whisper` as an optional dependency (`pip install openai-whisper` or `uv sync --extra asr`). Unlike images (which silently return empty), audio fails at pipeline init with a clear `ImportError`. This is a separate install/config issue, not a code fix. Future work: add `openai-whisper` to optional deps and handle the import gracefully.
