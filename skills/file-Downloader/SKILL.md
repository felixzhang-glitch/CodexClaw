---
name: file-downloader
description: Download articles, papers, docs, or webpages as local PDF and/or Markdown files. Use when the user asks to download a PDF, save an article/page/link as PDF or MD, fetch a paper by title or URL, or preserve an online page offline. Supports format selection (pdf/md/both) and auto-resolves native PDF links for academic sources (arXiv, ACL Anthology, OpenReview, NeurIPS).
---

# File Downloader

## Workflow

1. Identify the best source URL.
   - If the user gives a URL, use it directly.
   - If the user gives only a title, search the web and prefer official or primary sources.
2. Determine output format from user intent:
   - `pdf` — PDF only
   - `md` — Markdown only
   - `both` — PDF + sibling .md (default when unspecified)
3. Run the bundled script (SKILL_DIR = this skill's directory):

```bash
bun "$SKILL_DIR/tools/download-pdf.js" "$URL" --format both --output-dir output/pdf
```

4. Validate the result:
   - Check file size; confirm PDF is non-empty.
   - Confirm the title/source URL appears in generated offline files.
5. Reply with absolute clickable file paths and note whether the file was directly downloaded (native PDF) or generated from webpage content.

## Academic Sources

The script auto-resolves landing pages to native PDF links before fetching:

- arXiv: `arxiv.org/abs/{id}` -> `arxiv.org/pdf/{id}.pdf`
- ACL Anthology: `aclanthology.org/{id}` -> `.pdf` suffix
- OpenReview: `openreview.net/forum?id={id}` -> `openreview.net/pdf?id={id}`
- NeurIPS: `proceedings.neurips.cc/paper_files/paper/{id}` -> `/file` suffix

When a native PDF is found, the original PDF is downloaded as-is (no re-generation). If the user requests `--format md` for a native-PDF-only source, the script exits with an error; fall back to the Blocked Pages flow below if MD is required.

## Blocked Pages

Some sites block direct requests but are still readable through browser/search tooling. If the script fails with `403`, challenge pages, empty content, or missing article text:

1. Use browsing/search to retrieve the article text from the official page.
2. Save a temporary Markdown file with title, source URL, date/author if known, headings, paragraphs, bullets, code blocks, tables, and image captions.
3. Convert it with:

```bash
bun "$SKILL_DIR/tools/download-pdf.js" --markdown tmp/article.md --source-url "$URL" --format both --output-dir output/pdf --filename article-name
```

This fallback is an offline webpage capture, not an official PDF. Say that clearly.

## Script Notes

- `--format {pdf,md,both}` controls output; default `both`.
- `--filename name` for stable names (extension appended automatically per format).
- `--title "Title"` when the source page lacks a clean title.
- Markdown output uses proper pipe-table syntax for HTML tables.
- The script chooses reader-friendly fonts automatically: English pages prefer Helvetica with LTR wrapping; CJK-heavy pages use CJK-capable fonts with CJK wrapping; mixed pages use Unicode TTF when available.
- If a generated PDF looks cramped, regenerate with the current script before manual fixes.
- For pages with dynamic images or video, preserve captions/source links rather than embedding media unless the user asks for a visual archive.
