---
type: note
title: Obsidian Markdown Rules
---
# Obsidian Markdown Rules

Rules for writing valid Obsidian Flavored Markdown in vault files.
Source: adapted from kepano/obsidian-skills (MIT).

## Wiki-Links

```markdown
[[Note Name]]                    Basic link
[[Note Name|Display Text]]       Link with alias
[[Note Name#Heading]]            Link to heading
[[#Heading in same note]]        Same-note heading link
[[Note Name#^block-id]]          Link to block
```

### Block References

Add `^block-id` at end of any paragraph to make it linkable:

```markdown
This paragraph can be linked to. ^my-block

> Quote block content
^quote-id
```

Then link with `[[Note#^my-block]]`.

## Embeds

```markdown
![[Note Name]]                   Embed full note
![[Note Name#Heading]]           Embed section
![[image.png]]                   Embed image
![[image.png|300]]               Image with width
![[image.png|640x480]]           Image with dimensions
![[document.pdf#page=3]]         PDF page
```

## Callouts

```markdown
> [!note]
> Basic note callout.

> [!warning] Custom Title
> Warning with title.

> [!tip]- Collapsed by default
> Foldable content.
```

### Types we should use in vault:

| Type | When to use |
|------|-------------|
| `[!warning]` | Blockers, risks, urgent items |
| `[!info]` | Context, background info |
| `[!tip]` | Recommendations, best practices |
| `[!todo]` | Action items |
| `[!success]` | Wins, completed milestones |
| `[!question]` | Open questions |
| `[!example]` | Examples, templates |

## Tables with Wiki-Links

Escape pipes inside wiki-links in tables:

```markdown
| Client | Link |
|--------|------|
| Client | [[business/crm/acme-corp\|Acme Corp]] |
```

## Comments

Obsidian-native comments (hidden in reading view):

```markdown
%%This is hidden in reading view%%

%%
Multi-line hidden block.
Only visible in edit mode.
%%
```

Use `%%` for Obsidian, `<!-- -->` for HTML-compatible comments.
Our processing markers (`<!-- processed -->`) stay as HTML comments since they're parsed by scripts.

## Tags

Valid tag characters:
- Letters (any language), numbers, `_`, `-`, `/`
- Numbers cannot be first character
- `/` creates nested tags: `#business/client`

```markdown
#tag #nested/tag #tag-with-dashes

# In frontmatter:
tags:
  - tag1
  - nested/tag2
```

## Properties (Frontmatter)

### Types

| Type | Example |
|------|---------|
| Text | `title: My Title` |
| Number | `rating: 4.5` |
| Checkbox | `completed: true` |
| Date | `date: 2024-01-15` |
| Date+Time | `due: 2024-01-15T14:30:00` |
| List | `tags: [one, two]` |
| Links | `related: "[[Other Note]]"` |

### Default properties (special meaning in Obsidian)

- `tags` — searchable tags
- `aliases` — alternative names (found via search/link autocomplete)
- `cssclasses` — custom CSS classes

## Escaping

```markdown
\*not italic\*
\#not heading
1\. not a list
```

## Footnotes

```markdown
Text with footnote[^1].

[^1]: Footnote content.

Inline footnote^[content here].
```

## Do NOT

- Use `%%` comments for processing markers (keep `<!-- -->` for scripts)
- Use block references (`^id`) in daily notes (too granular)
- Add `aliases` to CRM files (use wiki-link aliases instead)
- Use Mermaid/LaTeX unless specifically needed
