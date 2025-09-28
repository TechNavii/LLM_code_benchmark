# Task: Harden client-side form validation

The registration form in `index.html` has a brittle validation layer (`static/app.js`). Users can enter a variety of invalid inputs (Unicode emails, trailing whitespace, overly long interests, repeated spaces, emoji-only interests, etc.), and the current logic does not sanitize or normalize fields correctly. Write robust validation that meets the following requirements:

- Email validation: must be case-insensitive, trim whitespace, and reject addresses with multiple consecutive dots, missing domain segments, or Unicode control characters.
- Password: minimum 8 characters, must contain upper, lower, digit, and symbol categories; reject passwords sharing 80% or more similarity to the email local-part (Levenshtein similarity check required client-side).
- Confirm: match normalized password.
- Interests: allow multi-line input; trim each line, collapse multiple spaces, and limit to 150 characters overall; reject interests containing banned keywords (defined in `tests/banned_keywords.json`).
- Error messages must be accessible: render as a list in `#form-status`, use `role="alert"`, add `aria-invalid` to offending fields, and focus the first invalid field.
- Rate-limit submissions: ignore repeat submissions if the last successful submission was less than 5 seconds ago (store timestamp in closure).

Use modern ES modules (no global variables). Keep logic testable by exporting individual validation helpers. Do not remove existing structure; update JS/CSS/HTML as needed to satisfy tests.

## Testing
```
node tests/run-tests.js
```
