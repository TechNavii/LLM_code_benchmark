from __future__ import annotations

import zlib

from harness.expert_questions.dataset import _iter_pdf_streams


def test_iter_pdf_streams_skips_invalid_streams() -> None:
    good = zlib.compress(b"hello")
    bad = b"not-a-zlib-stream"

    data = b"stream\n" + good + b"\nendstream\n" b"stream\n" + bad + b"\nendstream\n"

    streams = list(_iter_pdf_streams(data))
    assert streams == [b"hello"]
