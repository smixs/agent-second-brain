# Phase 2: EXECUTE

Read capture.json from Phase 1. Record tasks in the vault, save thoughts, update CRM.

## Input
- `.session/capture.json` — output from Phase 1
- `business/_index.md` — business context
- `projects/_index.md` — projects context

## Task

### 1. Record tasks in the vault

For each entry with `classification: "task"`, add a checklist entry to the
daily note (or the relevant project note):

```markdown
## Tasks
- [ ] {task} (due: {date}, priority: {p1-p4})
```

### 2. Save thoughts

For each entry with classification idea/reflection/learning/project:
- Create file in `thoughts/{category}/YYYY-MM-DD-slug.md`
- Include frontmatter with description field (retrieval filter, ~150 chars)
- Add wiki-links to related entities
- Add typed relationships in Related section:
  ```markdown
  ## Related
  - [[business/crm/acme-corp|Acme Corp]] — context: discussed during project review
  ```

### 4. Update CRM

For entries with `classification: "crm_update"`:
- Update relevant `business/crm/*.md` or `projects/clients/*.md`
- Update deal_status, status, or add notes

### 5. Build links

For all created/updated files:
- Search for related notes in vault
- Add wiki-links with context phrases
- Update frontmatter `related:[]`



## Output Format

Print ONLY valid JSON:

```json
{
  "tasks_created": [
    {"id": "8501234567", "content": "Follow-up Acme Corp", "priority": 2, "due": "tomorrow"}
  ],
  "thoughts_saved": [
    {"path": "thoughts/ideas/2026-02-19-layered-memory.md", "title": "AI agents need layered memory", "category": "ideas"}
  ],
  "crm_updated": [
    {"path": "business/crm/acme-corp.md", "change": "Added meeting note"}
  ],
  "links_created": [
    {"from": "thoughts/ideas/2026-02-19-layered-memory.md", "to": "business/crm/acme-corp.md", "context": "discussed during project review"}
  ],
  "process_goals": {
    "active": 5,
    "overdue": 1,
    "created": 0
  },
  "workload": {
    "mon": 3, "tue": 2, "wed": 4, "thu": 1, "fri": 2, "sat": 0, "sun": 0
  },
  "observations": []
}
```
