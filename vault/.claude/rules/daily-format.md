---
paths: "daily/**/*.md"
---

# Daily Notes Format

Rules for daily capture files in `daily/` folder.

## File Naming

- Format: `YYYY-MM-DD.md`
- Example: `2024-12-20.md`
- One file per day

## Entry Format

Each entry follows this structure:

```markdown
## HH:MM [type]
Content of the entry
```

### Entry Types

| Type | Description |
|------|-------------|
| `[voice]` | Transcribed voice message |
| `[text]` | Direct text message |
| `[forward from: Name]` | Forwarded message with source |
| `[photo]` | Image with embed |

### Photo Entries

Photos include Obsidian embed:

```markdown
## 14:30 [photo]
![[attachments/2024-12-20/img-143025.jpg]]

Optional description or transcribed text from photo
```

## Processing Rules

When processing daily files:

1. **Read chronologically** — entries are timestamped
2. **Classify each entry** — task, idea, reflection, learning, project
3. **Check for photos** — analyze with vision if present
4. **Extract actionable items** — add task entries to the daily note
5. **Save valuable thoughts** — move to `thoughts/` categories
6. **Mark as processed** — after successful processing

## Do NOT

- Modify original entries
- Delete entries before archiving
- Change timestamps
- Add content between entries

## After Processing

Add processing marker at end of file:

```markdown
---
processed: 2024-12-20T21:00:00
thoughts: 3
tasks: 2
---
```
