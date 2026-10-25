"""Open-set identity matching shared by the app, recognition service, and evaluation.

Rules:
1. Cosine similarity on L2-normalized embeddings.
2. Gallery filtering by session roster / allowed student IDs.
3. Multi-sample aggregation: scores are grouped by student ID (taking max over samples).
4. Top-1 vs Top-2 margin is strictly computed between two DIFFERENT student IDs.
5. Decision requires score >= threshold AND margin >= min_margin.
"""
from typing import Dict, Optional, Set
import numpy as np
from functions.identity import parse_student_folder


def l2_normalize(x, axis=-1):
    x = np.asarray(x, dtype=np.float32)
    norm = np.linalg.norm(x, axis=axis, keepdims=True)
    norm = np.where(norm < 1e-12, 1e-12, norm)
    return x / norm


def identity_scores(
    embedding: np.ndarray,
    gallery: Dict[str, np.ndarray],
) -> Dict[str, dict]:
    """Calculate best cosine score per unique student ID across all enrolled samples.

    Args:
        embedding: (d,) or (1, d) probe embedding vector.
        gallery: {folder_or_identity: (n_samples, d) array of enrolled embeddings}.

    Returns:
        dict of { student_id: {'score': float, 'identity': folder_name, 'student_id': sid} }
    """
    probe = l2_normalize(np.asarray(embedding, dtype=np.float32).reshape(-1))
    dim = probe.shape[0]

    scores_by_sid: Dict[str, dict] = {}

    for folder_key, stored in gallery.items():
        # Parse student ID from folder (e.g. CLASS_ID_Name or raw ID)
        parsed = parse_student_folder(folder_key)
        sid = (parsed.get('id') or folder_key).strip().upper()

        stored_arr = np.atleast_2d(stored)
        if stored_arr.shape[1] != dim:
            continue

        # Cosine similarity between L2-normalized vectors
        sims = l2_normalize(stored_arr, axis=1) @ probe
        max_sim = float(sims.max())

        # Aggregate by student ID: keep highest similarity and matching folder
        if sid not in scores_by_sid or max_sim > scores_by_sid[sid]['score']:
            scores_by_sid[sid] = {
                'score': max_sim,
                'identity': folder_key,
                'student_id': sid,
                'parsed': parsed,
            }

    return scores_by_sid


def decide(
    scores_by_sid: Dict[str, dict],
    threshold: float,
    min_margin: float,
    allowed_student_ids: Optional[Set[str]] = None,
) -> dict:
    """Apply the open-set rule to per-student scores.

    Candidate selection:
    1. Top-1 candidate is the student ID with the highest similarity score.
    2. Top-2 candidate MUST belong to a DIFFERENT student ID.
    3. Check ambiguity: if top1_score >= threshold and (top1 - top2) < min_margin, mark ambiguous.
    4. Session roster filtering: top-1 candidate must be in allowed_student_ids (if provided).
    5. Accept top-1 only if score >= threshold AND (top-1 - top-2) >= min_margin AND in roster.
    """
    if not scores_by_sid:
        return {
            'matched': False,
            'identity': None,
            'best_identity': None,
            'student_id': None,
            'score': 0.0,
            'margin': 0.0,
            'ambiguous': False,
        }

    # Rank distinct students by score
    ranked = sorted(scores_by_sid.values(), key=lambda item: item['score'], reverse=True)
    top1 = ranked[0]
    top1_score = top1['score']
    best_id = top1['identity']
    best_sid = top1['student_id']

    # Top-2 candidate is guaranteed to be a different student ID
    second_score = ranked[1]['score'] if len(ranked) > 1 else -1.0
    margin = (top1_score - second_score) if len(ranked) > 1 else 1.0

    ambiguous = (top1_score >= threshold) and (margin < min_margin)

    # Allowed student IDs check (session roster)
    in_roster = (allowed_student_ids is None) or (best_sid in allowed_student_ids)

    matched = (top1_score >= threshold) and (margin >= min_margin) and in_roster

    return {
        'matched': matched,
        'identity': best_id if matched else None,
        'best_identity': best_id,
        'student_id': best_sid if matched else None,
        'best_student_id': best_sid,
        'score': round(float(top1_score), 4),
        'margin': round(float(margin), 4),
        'ambiguous': ambiguous,
    }


def match(
    embedding: np.ndarray,
    gallery: Dict[str, np.ndarray],
    threshold: float,
    min_margin: float,
    allowed_student_ids: Optional[Set[str]] = None,
) -> dict:
    scores = identity_scores(embedding, gallery)
    return decide(scores, threshold, min_margin, allowed_student_ids=allowed_student_ids)
