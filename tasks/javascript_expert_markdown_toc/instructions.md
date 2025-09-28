# JavaScript Expert Task: Markdown Table of Contents

Implement `generateToc(markdown, options = {})` in `workspace/toc.js`.

Requirements:

- Return an array of nested heading nodes in document order. Each node has:
  ```js
  {
    level: number,   // heading level (1-6)
    text: string,    // normalised heading text
    slug: string,    // unique slug for hyperlink ids
    children: []     // headings nested underneath this heading
  }
  ```
- `options.minDepth` and `options.maxDepth` (defaults 1 and 6) restrict which headings appear. Levels outside the range are ignored but still influence nesting.
- Generate slugs using `options.slugify(text, index)` when provided. The fallback should:
  - Lowercase ASCII letters.
  - Strip punctuation except hyphen and space.
  - Collapse whitespace to single hyphen.
  - Append `-N` to preserve uniqueness when duplicates appear.
- Ignore headings inside fenced code blocks (```), HTML comments, or indented code blocks.
- Trim inline trailing `#` fragments and Markdown emphasis markers while preserving meaningful Unicode characters.
- Maintain hierarchical structure: an `h3` following an `h1` should nest under the closest preceding heading of lower level.

The test-suite validates slug uniqueness, code block filtering, depth constraints, and nested structures.
