# Markdown Specification Loader (`MarkdownLoader.md`)

**Version**: 1.0.0  
**Module**: `backend.core.markdown` / `backend.markdown_engine`  

---

## 1. Overview

The **Markdown Loader** (`markdown_loader`) is the core engine component responsible for loading, parsing, caching, and validating agent prompt specifications and workflow documents written in Markdown.

---

## 2. YAML Frontmatter Parsing

Every agent prompt file begins with a YAML metadata header enclosed in triple dashes (`---`).

```markdown
---
name: "AcademicResearcher"
department: "Research"
role: "Specialist analyzing peer-reviewed journals, historical archives, and literature."
inputs: ["topic_query", "academic_filters"]
outputs: ["academic_dossier"]
dependencies: ["ResearchAgent"]
permissions: ["read_write_knowledge"]
version: "1.0.0"
---
```

---

## 3. Parsed Document Data Structure

When `markdown_loader.load(filepath)` is invoked, it returns a `MarkdownDocument` object:

```python
class MarkdownDocument:
    filepath: str
    frontmatter: Dict[str, Any]  # Key-value dictionary parsed from YAML header
    content: str                  # Markdown body text
    sections: Dict[str, str]      # Parsed H1/H2 markdown sections
```

---

## 4. Section Extraction Protocol

The loader automatically splits markdown content into discrete named sections:
- `## 1. Identity`
- `## 2. Mission`
- `## 3. Purpose`
- `## 23. Prompt Template`
- `## 24. JSON Input Schema`
- `## 25. JSON Output Schema`

This enables runtime engines to extract the system prompt template (`## 23. Prompt Template`) or JSON validation schemas programmatically.

---

## 5. Performance Caching

To eliminate redundant disk I/O during heavy workflow execution, `markdown_loader` maintains an in-memory LRU cache keyed by file path and file modification timestamp (`mtime`). If the file on disk is modified, the cache invalidates automatically.
