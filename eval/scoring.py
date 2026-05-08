"""Scoring helpers for the evaluation harness.

citation_accuracy dimension scorer validates that every sentence in
final_answer has a corresponding entry in provenance_map. Missing entries
penalize the citation_accuracy score.
"""
from __future__ import annotations

from typing import Any


def score_citation_accuracy(
    final_answer: str,
    provenance_map: list[dict[str, Any]],
    *,
    base_score: float = 0.9,
) -> dict[str, Any]:
    """Validate provenance_map coverage against final_answer sentences.

    Returns a dict with ``score`` (float 0-1) and ``justification`` (str).

    Penalises 0.1 per sentence in final_answer that lacks a provenance_map
    entry.  The score floor is 0.0.
    """
    if not final_answer:
        return {"score": 0.0, "justification": "No final_answer to evaluate."}

    sentences = [s.strip() for s in final_answer.split(".") if s.strip()]
    if not sentences:
        return {"score": base_score, "justification": "No sentence boundaries detected; skipping coverage check."}

    # Build lookup from sentence_index -> entry
    indexed = {entry.get("sentence_index"): entry for entry in provenance_map}
    missing_indices: list[int] = []
    missing_texts: list[str] = []

    for idx, sentence in enumerate(sentences):
        if idx not in indexed:
            missing_indices.append(idx)
            missing_texts.append(sentence[:80])

    missing_count = len(missing_indices)
    if missing_count == 0:
        return {
            "score": base_score,
            "justification": (
                f"All {len(sentences)} sentence(s) have corresponding provenance_map entries. "
                f"Citation coverage is complete."
            ),
        }

    penalty = min(base_score, missing_count * 0.1)
    final_score = max(0.0, base_score - penalty)
    missing_desc = "; ".join(f'[{i}] "{t}..."' for i, t in zip(missing_indices, missing_texts))
    return {
        "score": final_score,
        "justification": (
            f"{missing_count} sentence(s) in final_answer lack provenance_map entries "
            f"(penalised {penalty:.1f}): {missing_desc}"
        ),
    }


def validate_provenance_map(provenance_map: list[dict[str, Any]]) -> list[str]:
    """Return a list of validation errors in the provenance_map structure.

    Each entry must have: sentence_index (int), text (str), source_agent (str),
    chunk_id (str|None).
    """
    errors: list[str] = []
    required_keys = {"sentence_index", "text", "source_agent"}
    for i, entry in enumerate(provenance_map):
        missing = required_keys - set(entry.keys())
        if missing:
            errors.append(f"Entry [{i}] missing keys: {missing}")
        if "chunk_id" not in entry:
            errors.append(f"Entry [{i}] missing 'chunk_id' key (may be null)")
    return errors
