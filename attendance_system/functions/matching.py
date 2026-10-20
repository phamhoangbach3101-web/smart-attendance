"""Open-set identity matching shared by the app and the evaluation script.

Keeping the decision rule in one pure function guarantees that the numbers
reported by evaluate.py describe exactly what the attendance app does.
"""
import numpy as np


def l2_normalize(x, axis=-1):
    x = np.asarray(x, dtype=np.float32)
    return x / (np.linalg.norm(x, axis=axis, keepdims=True) + 1e-6)


def identity_scores(embedding, gallery):
    """Best cosine score per identity.

    embedding: (d,) or (1, d) probe embedding.
    gallery:   {identity: (n_samples, d) array of enrolled embeddings}.
    Returns {identity: max cosine similarity over that identity's samples}.
    """
    probe = l2_normalize(np.asarray(embedding).reshape(-1))
    scores = {}
    for identity, stored in gallery.items():
        stored = np.atleast_2d(stored)
        if stored.shape[1] != probe.shape[0]:
            continue
        scores[identity] = float((l2_normalize(stored, axis=1) @ probe).max())
    return scores


def decide(scores, threshold, min_margin):
    """Apply the open-set rule to per-identity scores.

    Accept the best identity only if its score >= threshold AND it beats the
    second-best identity by at least min_margin. Otherwise reject (unknown).
    """
    if not scores:
        return {'matched': False, 'identity': None, 'score': 0.0,
                'margin': 0.0, 'ambiguous': False}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_id, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else -1.0
    margin = best - second if len(ranked) > 1 else 1.0
    matched = best >= threshold and margin >= min_margin
    return {
        'matched': matched,
        'identity': best_id if matched else None,
        'best_identity': best_id,
        'score': round(best, 4),
        'margin': round(margin, 4),
        'ambiguous': best >= threshold and margin < min_margin,
    }


def match(embedding, gallery, threshold, min_margin):
    return decide(identity_scores(embedding, gallery), threshold, min_margin)
