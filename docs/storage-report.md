# Disk usage

**Reclaimed now: 281.7 MiB** by removing regenerable Python bytecode. Source code, installed libraries, speech models, meeting records and outputs were retained. Python may recreate some bytecode as needed.

| Main component | Disk space |
| --- | ---: |
| Python libraries before cleanup | 1,653.1 MiB |
| Python libraries now | 1,371.4 MiB |
| Whisper speech model | 1,539.2 MiB |
| Kokoro voice model | 337.4 MiB |
| Meeting history and outputs | 599.4 MiB |

Most space is local speech software and model weights, rather than meeting history.

**Another 267.5 MiB can be reclaimed after restarting the app:** open the corridor → Settings → Storage → Compact meeting files.

| Cleanup | Reclaimable |
| --- | ---: |
| Identical archived files (including repeated PDFs) | 153.9 MiB |
| Regenerable PDF page images | 113.6 MiB |

The cleanup keeps all meeting text, checkpoints, attachments, file contents and file paths. Identical immutable archive files share storage. Page images are regenerated from retained PDFs when needed; open rooms keep their current page caches. The existing meeting directories have only been audited, not modified.

Future shares reuse identical archive copies, temporary uploads are removed after sharing, and closing a room clears its PDF page cache.

Validation: 36 Python checks passed, including compaction, content preservation, failures, authentication and active-room cache preservation. Frontend syntax and live dictation checks passed.

Command-line alternative, with the app closed: `./run.sh storage --compact`.
