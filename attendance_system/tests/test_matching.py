"""Unit tests for the open-set decision rule (no models or camera needed).

    cd attendance_system
    python -m pytest tests
"""
import numpy as np
import pytest

from functions.matching import decide, identity_scores, match


def sc(**scores):
    """decide() input: {student_id: {'score', 'identity', 'student_id'}}."""
    return {k: {'score': v, 'identity': k, 'student_id': k} for k, v in scores.items()}


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def gallery():
    rng = np.random.default_rng(0)
    base = {name: unit(rng.normal(size=512)) for name in ('A', 'B', 'C')}
    # Three enrollment samples per identity, each a small perturbation.
    return {name: np.vstack([unit(v + 0.02 * rng.normal(size=512)) for _ in range(3)])
            for name, v in base.items()}, base


def test_known_person_is_matched(gallery):
    g, base = gallery
    result = match(base['B'], g, threshold=0.6, min_margin=0.08)
    assert result['matched'] and result['identity'] == 'B'


def test_unknown_person_is_rejected(gallery):
    g, _ = gallery
    stranger = unit(np.random.default_rng(1).normal(size=512))
    result = match(stranger, g, threshold=0.6, min_margin=0.08)
    assert not result['matched'] and result['identity'] is None


def test_score_uses_best_sample_per_identity(gallery):
    g, base = gallery
    scores = identity_scores(g['A'][1], g)
    assert scores['A']['score'] == pytest.approx(1.0, abs=1e-4)


def test_small_margin_is_ambiguous():
    result = decide(sc(A=0.72, B=0.69), threshold=0.6, min_margin=0.08)
    assert not result['matched'] and result['ambiguous']


def test_single_identity_has_full_margin():
    result = decide(sc(A=0.65), threshold=0.6, min_margin=0.08)
    assert result['matched'] and result['margin'] == 1.0


def test_below_threshold_is_rejected():
    result = decide(sc(A=0.55, B=0.10), threshold=0.6, min_margin=0.08)
    assert not result['matched'] and not result['ambiguous']


def test_empty_gallery():
    assert decide({}, 0.6, 0.08)['matched'] is False


def test_dimension_mismatch_is_skipped():
    scores = identity_scores(np.ones(512), {'old': np.ones((2, 128)), 'new': np.ones((1, 512))})
    assert set(scores) == {'NEW'}         # keys are upper-cased student IDs


def test_same_student_in_two_folders_is_not_ambiguous(gallery):
    g, base = gallery
    g2 = {'C1_S1_An': g['A'], 'C2_S1_An': g['A'][:1], 'C1_S2_Binh': g['B']}
    result = match(base['A'], g2, threshold=0.6, min_margin=0.08)
    assert result['matched'] and result['student_id'] == 'S1'


def test_roster_filter_rejects_student_outside_session(gallery):
    g, base = gallery
    result = match(base['A'], g, threshold=0.6, min_margin=0.08, allowed_student_ids={'B', 'C'})
    assert not result['matched'] and result['best_student_id'] == 'A'
