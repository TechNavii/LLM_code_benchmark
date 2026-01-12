from __future__ import annotations


from harness.expert_questions import run_benchmark


def test_extract_single_line_answer_strips_answer_prefix() -> None:
    assert run_benchmark._extract_single_line_answer("Answer: Map") == "Map"
    assert run_benchmark._extract_single_line_answer("Final answer: Map") == "Map"
    assert run_benchmark._extract_single_line_answer("- Answer: `Map`.") == "Map"
