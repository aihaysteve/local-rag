# Benchmark Results

## Summary (avg total seconds per file)

| Configuration | m1-4070-vlm-offload | m1_4070 | smoke-test |
|---|---|---|---|
| balanced | - | 27.7s | - |
| fast | - | 6.1s | 8.0s |
| quality | 8.4s | 31.2s | - |

## Model Load Times

| Model | Type | Load Time | VRAM/RAM |
|---|---|---|---|
| bge-m3 | embedding | 1.5s | 1.1 GB |

## Audio

| Fixture | Size | m1-4070-vlm-offload/quality | m1_4070/balanced | m1_4070/fast | m1_4070/quality | smoke-test/fast |
|---|---|---|---|---|---|---|
| audio-30s.mp3 | 374 KB | 23ms | 5.6s | 2.0s | 10.2s | 2.3s |
| audio-5min.mp3 | 2.1 MB | 7ms | 16.7s | 3.8s | 36.3s | 4.1s |

## Image

| Fixture | Size | m1-4070-vlm-offload/quality | m1_4070/balanced | m1_4070/fast | m1_4070/quality | smoke-test/fast |
|---|---|---|---|---|---|---|
| image-diagram.png | 332 KB | 6.4s | 8.7s | 6.4s | 18.4s | 7.7s |
| image-photo.jpg | 1.8 MB | 31.3s | 36.4s | 29.1s | 35.2s | 33.6s |

## Lightweight

| Fixture | Size | m1-4070-vlm-offload/quality | m1_4070/balanced | m1_4070/fast | m1_4070/quality | smoke-test/fast |
|---|---|---|---|---|---|---|
| README.md | 1 KB | 1.2s | 530ms | 845ms | 321ms | 974ms |
| epub-short.epub | 626 KB | 2.9s | 3.5s | 2.0s | 3.7s | 1.7s |
| markdown-5pg.md | 17 KB | 749ms | 573ms | 422ms | 629ms | 1.6s |
| plaintext-10kb.txt | 11 KB | 279ms | 312ms | 190ms | 335ms | 209ms |

## Office

| Fixture | Size | m1-4070-vlm-offload/quality | m1_4070/balanced | m1_4070/fast | m1_4070/quality | smoke-test/fast |
|---|---|---|---|---|---|---|
| docx-5pg.docx | 1.3 MB | 585ms | 996ms | 781ms | 802ms | 520ms |
| pptx-10slides.pptx | 1.9 MB | 816ms | 1.1s | 817ms | 1.1s | 4.1s |

## Pdf

| Fixture | Size | m1-4070-vlm-offload/quality | m1_4070/balanced | m1_4070/fast | m1_4070/quality | smoke-test/fast |
|---|---|---|---|---|---|---|
| pdf-10pg-mixed.pdf | 882 KB | 22.6s | 71.5s | 8.1s | 88.3s | 8.8s |
| pdf-1pg-text.pdf | 70 KB | 1.0s | 14.3s | 1.3s | 7.5s | 2.3s |
| pdf-50pg-dense.pdf | 964 KB | 41.5s | 199.5s | 23.8s | 203.4s | 36.8s |
