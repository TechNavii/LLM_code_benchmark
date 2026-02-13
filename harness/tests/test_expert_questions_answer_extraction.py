from __future__ import annotations


from harness.expert_questions import run_benchmark


def test_extract_single_line_answer_strips_answer_prefix() -> None:
    assert run_benchmark._extract_single_line_answer("Answer: Map") == "Map"
    assert run_benchmark._extract_single_line_answer("Final answer: Map") == "Map"
    assert run_benchmark._extract_single_line_answer("- Answer: `Map`.") == "Map"


def test_extract_single_line_answer_prefers_short_line_over_explanation() -> None:
    raw = "Bob\nBecause Alice cannot say both are liars."
    assert run_benchmark._extract_single_line_answer(raw) == "Bob"


def test_extract_single_line_answer_handles_reasoning_then_answer() -> None:
    raw = "Analyze the request\nWe should solve it step by step.\nBob"
    assert run_benchmark._extract_single_line_answer(raw) == "Bob"


def test_extract_single_line_answer_strips_think_blocks() -> None:
    raw = "<think>Analyze the request\nReasoning here</think>\nBob"
    assert run_benchmark._extract_single_line_answer(raw) == "Bob"


def test_extract_single_line_answer_skips_meta_headers() -> None:
    raw = "Analyze the Request:\nEvaluate Possibilities:\nBob"
    assert run_benchmark._extract_single_line_answer(raw) == "Bob"


def test_extract_single_line_answer_strips_inline_think_tags() -> None:
    raw = "Final Output Generation: Bob</think>Bob"
    assert run_benchmark._extract_single_line_answer(raw) == "Bob"


def test_extract_single_line_answer_skips_validation_lines() -> None:
    raw = "Final validation\nBob"
    assert run_benchmark._extract_single_line_answer(raw) == "Bob"


def test_extract_single_line_answer_handles_result_prefix_and_dedup() -> None:
    raw = "Result: Hisson</think>Hisson"
    assert run_benchmark._extract_single_line_answer(raw) == "son"
