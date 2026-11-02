# Automatic meeting compaction

| Meeting state | Storage behavior |
| --- | --- |
| Closed | Automatically deduplicate identical archived files and clear regenerable PDF page images |
| Open | Excluded from compaction; files and page previews stay untouched |
| App quits | Each meeting is compacted as it closes |

Meeting history, checkpoints, attachments, shared file contents and file paths are preserved. Cleanup errors do not prevent a meeting from being saved and closed.

The manual cleanup button remains in corridor Settings → Storage as **Compact closed meetings now**.

Validation: 38 Python checks passed, including automatic close-time cleanup, open-meeting exclusion and cleanup failure handling. Corridor JavaScript syntax passed.

Restart the app to activate the default behavior.
