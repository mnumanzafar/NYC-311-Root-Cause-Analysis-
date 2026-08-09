import numpy as np
import pytest

from src.analysis.hypothesis_tests import (
    benjamini_hochberg, chi_square_independence, two_proportion_ztest, welch_ttest,
)


def test_identical_proportions_not_significant():
    r = two_proportion_ztest(500, 1000, 500, 1000)
    assert r.p_value == pytest.approx(1.0)
    assert not r.significant


def test_large_proportion_gap_is_significant():
    r = two_proportion_ztest(300, 1000, 500, 1000, alpha=0.01)
    assert r.significant and r.p_value < 0.01
    assert r.detail["diff"] == pytest.approx(-0.2)


def test_zero_sample_size_raises():
    with pytest.raises(ValueError):
        two_proportion_ztest(1, 0, 1, 10)


def test_chi_square_detects_dependence():
    r = chi_square_independence([[400, 600], [600, 400]])
    assert r.significant
    assert 0 <= r.detail["cramers_v"] <= 1


def test_welch_ttest_on_shifted_normals():
    rng = np.random.default_rng(0)
    r = welch_ttest(rng.normal(100, 5, 200), rng.normal(90, 5, 200))
    assert r.significant


def test_benjamini_hochberg_controls_fdr():
    keep = benjamini_hochberg([0.0001, 0.002, 0.4, 0.9], alpha=0.01)
    assert keep[0] is True and keep[3] is False
