# HTML Expert Task: Heatmap Renderer

Implement `renderHeatmap(modelResults, options = {})` in `workspace/heatmap.js`.

- `modelResults` is an array of objects of the form:
  ```js
  {
    model: 'gpt-x',
    totals: { score: 21, percent: 58.3 },
    cells: [
      { id: 'q1', status: 'pass' },
      { id: 'q2', status: 'fail' },
      // ...
    ]
  }
  ```
- Return an HTML string representing an accessible heatmap table:
  - Use a `<table>` element with `<thead>` and `<tbody>`.
  - Include visually hidden text for screen readers describing colours (use `<span class="sr-only">`).
  - Each cell must have classes `heatmap-cell` and `status-${status}` and a `data-question` attribute.
  - Add row headers with the model name and summary cell containing the total score as `21 / 36 (58.3%)`.
- `options.palette` maps statuses to CSS class names (e.g. `{ pass: 'green', fail: 'red' }`). Apply as additional classes when provided.
- Escapes HTML special characters in model names and question ids.
- Omit empty rows and throw a `TypeError` if the input is not iterable.
- When `modelResults` is empty, still return a table element with empty `<thead>` and `<tbody>` sections.

Tests assert semantic structure, escaping, palette behaviour, and screen-reader text hints.
