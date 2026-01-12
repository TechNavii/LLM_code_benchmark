"""Fuzz/property-based tests for patch normalization and validation helpers.

Uses Hypothesis to generate random patch-like strings and ensure
_is_probably_valid_patch and _normalize_patch_format never crash.
"""

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from harness.run_harness import _is_probably_valid_patch, _normalize_patch_format


# --- Strategies for generating patch-like content ---

# Standard patch line prefixes
PATCH_PREFIXES = [
    "diff --git",
    "index ",
    "--- ",
    "+++ ",
    "@@ ",
    "+",
    "-",
    " ",
    "new file mode",
    "deleted file mode",
    "rename from",
    "rename to",
    "similarity index",
    "dissimilarity index",
    "Binary files",
    "\\ No newline at end of file",
]


@st.composite
def patch_line(draw: st.DrawFn) -> str:
    """Generate a single patch-like line."""
    prefix = draw(st.sampled_from(PATCH_PREFIXES))
    # Exclude surrogate characters (Cs) which can cause encoding issues
    suffix = draw(st.text(alphabet=st.characters(blacklist_categories=["Cs"]), max_size=100))
    return prefix + suffix


@st.composite
def hunk_header(draw: st.DrawFn) -> str:
    """Generate a hunk header line with various formats."""
    old_start = draw(st.integers(min_value=0, max_value=10000))
    old_len = draw(st.integers(min_value=0, max_value=1000))
    new_start = draw(st.integers(min_value=0, max_value=10000))
    new_len = draw(st.integers(min_value=0, max_value=1000))

    # Randomly include/exclude optional length parts
    include_old_len = draw(st.booleans())
    include_new_len = draw(st.booleans())

    old_part = f"-{old_start}" + (f",{old_len}" if include_old_len else "")
    new_part = f"+{new_start}" + (f",{new_len}" if include_new_len else "")

    # Optional function context suffix
    suffix = draw(st.text(max_size=50))
    if suffix:
        return f"@@ {old_part} {new_part} @@ {suffix}"
    return f"@@ {old_part} {new_part} @@"


@st.composite
def malformed_hunk_header(draw: st.DrawFn) -> str:
    """Generate malformed hunk headers to test robustness."""
    variants = [
        "@@",
        "@@ @@",
        "@@ - @@",
        "@@ -1 @@",
        "@@ +1 @@",
        "@@ -1 +1",
        "@@-1,1 +1,1@@",
        "@@ -abc +def @@",
        "@@ -1,1 +1,1 @@extra stuff",
        "  @@ -1,1 +1,1 @@",  # Leading whitespace
    ]
    return draw(st.sampled_from(variants))


@st.composite
def file_header(draw: st.DrawFn) -> str:
    """Generate file header lines."""
    filename = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_./", min_size=1, max_size=50))
    variant = draw(st.integers(min_value=0, max_value=2))
    if variant == 0:
        return f"--- a/{filename}"
    elif variant == 1:
        return f"+++ b/{filename}"
    else:
        return f"diff --git a/{filename} b/{filename}"


@st.composite
def content_line(draw: st.DrawFn) -> str:
    """Generate content lines (additions, deletions, context)."""
    prefix = draw(st.sampled_from(["+", "-", " ", ""]))
    content = draw(st.text(max_size=200))
    return prefix + content


@st.composite
def patch_like_text(draw: st.DrawFn) -> str:
    """Generate text that looks like a patch."""
    lines = []
    num_lines = draw(st.integers(min_value=0, max_value=50))

    for _ in range(num_lines):
        line_type = draw(st.integers(min_value=0, max_value=4))
        if line_type == 0:
            lines.append(draw(hunk_header()))
        elif line_type == 1:
            lines.append(draw(file_header()))
        elif line_type == 2:
            lines.append(draw(content_line()))
        elif line_type == 3:
            lines.append(draw(malformed_hunk_header()))
        else:
            lines.append(draw(patch_line()))

    return "\n".join(lines)


@st.composite
def random_binary_like(draw: st.DrawFn) -> str:
    """Generate random strings that might contain binary-like data."""
    return draw(st.binary(max_size=500).map(lambda b: b.decode("latin-1")))


# --- Fuzz tests for _is_probably_valid_patch ---


class TestIsProbablyValidPatchFuzz:
    """Fuzz tests for _is_probably_valid_patch."""

    @given(patch_like_text())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_never_crashes_on_patch_like_input(self, patch: str):
        """Ensure the function never crashes on patch-like input."""
        result = _is_probably_valid_patch(patch)
        assert isinstance(result, bool)

    @given(st.text(max_size=5000))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_never_crashes_on_arbitrary_text(self, text: str):
        """Ensure the function never crashes on arbitrary text."""
        result = _is_probably_valid_patch(text)
        assert isinstance(result, bool)

    @given(random_binary_like())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_never_crashes_on_binary_like_input(self, data: str):
        """Ensure the function handles binary-like input gracefully."""
        result = _is_probably_valid_patch(data)
        assert isinstance(result, bool)

    @given(st.lists(st.sampled_from(["+", "-", " ", "@@", "---", "+++"]), max_size=20))
    @settings(max_examples=100)
    def test_handles_prefix_only_lines(self, prefixes: list[str]):
        """Test handling of lines that are just prefixes."""
        patch = "\n".join(prefixes)
        result = _is_probably_valid_patch(patch)
        assert isinstance(result, bool)


# --- Fuzz tests for _normalize_patch_format ---


class TestNormalizePatchFormatFuzz:
    """Fuzz tests for _normalize_patch_format."""

    @given(patch_like_text())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_never_crashes_on_patch_like_input(self, patch: str):
        """Ensure the function never crashes on patch-like input."""
        result, synthetic = _normalize_patch_format(patch)
        assert isinstance(result, str)
        assert isinstance(synthetic, bool)

    @given(st.text(max_size=5000))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_never_crashes_on_arbitrary_text(self, text: str):
        """Ensure the function never crashes on arbitrary text."""
        result, synthetic = _normalize_patch_format(text)
        assert isinstance(result, str)
        assert isinstance(synthetic, bool)

    @given(random_binary_like())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_never_crashes_on_binary_like_input(self, data: str):
        """Ensure the function handles binary-like input gracefully."""
        result, synthetic = _normalize_patch_format(data)
        assert isinstance(result, str)
        assert isinstance(synthetic, bool)

    @given(hunk_header())
    @settings(max_examples=200)
    def test_handles_various_hunk_headers(self, header: str):
        """Test that various hunk header formats don't crash."""
        result, synthetic = _normalize_patch_format(header)
        assert isinstance(result, str)
        assert isinstance(synthetic, bool)
        # Normalized hunk headers should contain @@
        if header.strip().startswith("@@"):
            assert "@@" in result

    @given(malformed_hunk_header())
    @settings(max_examples=50)
    def test_handles_malformed_hunk_headers(self, header: str):
        """Test robustness against malformed hunk headers."""
        result, synthetic = _normalize_patch_format(header)
        assert isinstance(result, str)
        assert isinstance(synthetic, bool)

    @given(st.lists(hunk_header(), min_size=1, max_size=10))
    @settings(max_examples=100)
    def test_handles_multiple_hunks(self, headers: list[str]):
        """Test handling of multiple consecutive hunks."""
        patch = "\n".join(headers)
        result, synthetic = _normalize_patch_format(patch)
        assert isinstance(result, str)
        assert isinstance(synthetic, bool)


# --- Regression tests for edge cases ---


class TestPatchParserEdgeCases:
    """Regression tests for specific edge formats."""

    def test_empty_string(self):
        """Test empty string input."""
        assert _is_probably_valid_patch("") is False
        result, synthetic = _normalize_patch_format("")
        assert result == ""
        assert synthetic is False

    def test_only_whitespace(self):
        """Test whitespace-only input."""
        assert _is_probably_valid_patch("   \n\t\n  ") is False
        result, synthetic = _normalize_patch_format("   \n\t\n  ")
        assert isinstance(result, str)

    def test_missing_file_headers(self):
        """Test patch with hunk but no file headers."""
        patch = "@@ -1,3 +1,4 @@\n context\n-removed\n+added"
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        # Normalize recalculates hunk counts based on actual content
        assert "@@" in normalized
        assert "-removed" in normalized
        assert "+added" in normalized

    def test_malformed_hunk_counts(self):
        """Test hunk with incorrect line counts."""
        patch = """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,1 @@
 context
-removed
+added
+another"""
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert isinstance(normalized, str)
        assert synthetic is True  # Should detect mismatch

    def test_mixed_whitespace_indentation(self):
        """Test patch with mixed tabs and spaces."""
        patch = "@@\t-1,1 +1,1 @@\n\t context\n -removed\n\t+added"
        result, synthetic = _normalize_patch_format(patch)
        assert isinstance(result, str)

    def test_partial_diff_no_hunks(self):
        """Test partial diff with headers but no hunks."""
        patch = """diff --git a/file.txt b/file.txt
--- a/file.txt
+++ b/file.txt"""
        result = _is_probably_valid_patch(patch)
        # Headers exist but no hunks or content - function requires headers AND changes
        # or hunks AND changes, or at least 2 add/remove lines
        assert result is False  # Headers alone without hunks/changes not sufficient
        normalized, synthetic = _normalize_patch_format(patch)
        assert "diff --git" in normalized

    def test_only_additions(self):
        """Test patch with only additions."""
        patch = """+line1
+line2
+line3"""
        result = _is_probably_valid_patch(patch)
        # 3 additions should be enough
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert "+line1" in normalized

    def test_only_deletions(self):
        """Test patch with only deletions."""
        patch = """-line1
-line2
-line3"""
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert "-line1" in normalized

    def test_unicode_content(self):
        """Test patch with unicode content."""
        patch = """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,1 @@
-Hello 世界
+Hello 🌍"""
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert "世界" in normalized or "🌍" in normalized

    def test_very_long_lines(self):
        """Test patch with very long lines."""
        long_line = "x" * 10000
        patch = f"+{long_line}\n-{long_line}"
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert long_line in normalized

    def test_no_newline_at_end_marker(self):
        """Test handling of 'No newline at end of file' marker."""
        patch = """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,1 @@
-old
\\ No newline at end of file
+new"""
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert "\\ No newline at end of file" in normalized or "No newline" in normalized

    def test_multiple_files(self):
        """Test patch spanning multiple files."""
        patch = """diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1,1 +1,1 @@
-old1
+new1
diff --git a/file2.txt b/file2.txt
--- a/file2.txt
+++ b/file2.txt
@@ -1,1 +1,1 @@
-old2
+new2"""
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert "file1.txt" in normalized
        assert "file2.txt" in normalized

    def test_hunk_header_with_function_context(self):
        """Test hunk header with function name context."""
        patch = """--- a/file.py
+++ b/file.py
@@ -10,5 +10,6 @@ def my_function():
     pass"""
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert "my_function" in normalized

    def test_git_binary_patch_marker(self):
        """Test handling of binary file markers."""
        patch = """diff --git a/image.png b/image.png
Binary files a/image.png and b/image.png differ"""
        # Should recognize as patch-like (has header + binary marker)
        _ = _is_probably_valid_patch(patch)  # May be True or False, just shouldn't crash
        normalized, synthetic = _normalize_patch_format(patch)
        assert "Binary files" in normalized

    def test_rename_headers(self):
        """Test patch with rename headers."""
        patch = """diff --git a/old.txt b/new.txt
similarity index 100%
rename from old.txt
rename to new.txt"""
        _ = _is_probably_valid_patch(patch)  # May be True or False, just shouldn't crash
        normalized, synthetic = _normalize_patch_format(patch)
        assert "rename from" in normalized
        assert "rename to" in normalized

    def test_new_file_mode(self):
        """Test patch creating a new file."""
        patch = """diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+line1
+line2"""
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert "new file mode" in normalized

    def test_deleted_file_mode(self):
        """Test patch deleting a file."""
        patch = """diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1,2 +0,0 @@
-line1
-line2"""
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert "deleted file mode" in normalized

    def test_crlf_line_endings(self):
        """Test patch with CRLF line endings."""
        patch = "--- a/file.txt\r\n+++ b/file.txt\r\n@@ -1,1 +1,1 @@\r\n-old\r\n+new\r\n"
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert isinstance(normalized, str)

    def test_zero_length_hunk(self):
        """Test hunk with zero old or new length."""
        patch = """--- a/file.txt
+++ b/file.txt
@@ -1,0 +1,2 @@
+new1
+new2"""
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert isinstance(normalized, str)

    def test_leading_spaces_in_hunk_header(self):
        """Test hunk header with leading spaces."""
        patch = """--- a/file.txt
+++ b/file.txt
  @@ -1,1 +1,1 @@
-old
+new"""
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert "@@" in normalized

    def test_index_line(self):
        """Test patch with git index line."""
        patch = """diff --git a/file.txt b/file.txt
index abc123..def456 100644
--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,1 @@
-old
+new"""
        result = _is_probably_valid_patch(patch)
        assert result is True
        normalized, synthetic = _normalize_patch_format(patch)
        assert "index" in normalized

    def test_context_only_patch(self):
        """Test patch with only context lines (no changes)."""
        patch = """--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,3 @@
 line1
 line2
 line3"""
        result = _is_probably_valid_patch(patch)
        # Has headers but no additions/deletions
        assert result is True  # Has 2+ headers and hunk
        normalized, synthetic = _normalize_patch_format(patch)
        assert "line1" in normalized

    def test_trailing_newline_preservation(self):
        """Test that trailing newline is preserved."""
        patch = "@@ -1,1 +1,1 @@\n-old\n+new\n"
        normalized, synthetic = _normalize_patch_format(patch)
        assert normalized.endswith("\n")

    def test_no_trailing_newline(self):
        """Test patch without trailing newline."""
        patch = "@@ -1,1 +1,1 @@\n-old\n+new"
        normalized, synthetic = _normalize_patch_format(patch)
        assert not normalized.endswith("\n")
