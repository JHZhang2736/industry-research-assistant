"""Metrics 计算单测：构造已知 (true, pred) 对，验证 confusion / P / R / F1 / macro。"""
import pytest
from app.intent_eval.metrics import (
    confusion_matrix, per_class_metrics, accuracy, macro_f1, compute_level_metrics,
)
from app.intent_eval.types import ERROR_LABEL


def test_accuracy_basic():
    assert accuracy(["a", "b", "c"], ["a", "b", "c"]) == 1.0
    assert accuracy(["a", "b", "c"], ["a", "b", "x"]) == pytest.approx(2 / 3)
    assert accuracy([], []) == 0.0


def test_confusion_matrix_basic():
    cm = confusion_matrix(
        true=["a", "a", "b", "b", "c"],
        pred=["a", "b", "b", "a", "c"],
        classes=["a", "b", "c"],
    )
    assert cm["a"]["a"] == 1
    assert cm["a"]["b"] == 1
    assert cm["a"]["c"] == 0
    assert cm["b"]["a"] == 1
    assert cm["b"]["b"] == 1
    assert cm["c"]["c"] == 1


def test_confusion_matrix_with_error_label():
    """error 预测进入 <error> 桶，不属于任何真实类。"""
    cm = confusion_matrix(
        true=["a", "b"],
        pred=[ERROR_LABEL, "b"],
        classes=["a", "b"],
    )
    assert cm["a"][ERROR_LABEL] == 1
    assert cm["a"]["a"] == 0
    assert cm["b"]["b"] == 1


def test_per_class_metrics_perfect():
    cm = confusion_matrix(
        true=["a", "a", "b", "b"],
        pred=["a", "a", "b", "b"],
        classes=["a", "b"],
    )
    metrics = per_class_metrics(cm, classes=["a", "b"])
    assert metrics["a"].precision == 1.0
    assert metrics["a"].recall == 1.0
    assert metrics["a"].f1 == 1.0
    assert metrics["a"].support == 2


def test_per_class_metrics_mixed():
    # true:  a a a b b
    # pred:  a a b a b
    # class a: TP=2, FP=1, FN=1 → P=2/3, R=2/3, F1=2/3
    # class b: TP=1, FP=1, FN=1 → P=1/2, R=1/2, F1=1/2
    cm = confusion_matrix(
        true=["a", "a", "a", "b", "b"],
        pred=["a", "a", "b", "a", "b"],
        classes=["a", "b"],
    )
    metrics = per_class_metrics(cm, classes=["a", "b"])
    assert metrics["a"].precision == pytest.approx(2 / 3)
    assert metrics["a"].recall == pytest.approx(2 / 3)
    assert metrics["a"].f1 == pytest.approx(2 / 3)
    assert metrics["a"].support == 3
    assert metrics["b"].precision == pytest.approx(0.5)
    assert metrics["b"].recall == pytest.approx(0.5)
    assert metrics["b"].f1 == pytest.approx(0.5)
    assert metrics["b"].support == 2


def test_per_class_metrics_zero_prediction():
    """某类从未被预测 → precision 分母 0，返回 0.0。"""
    cm = confusion_matrix(
        true=["a", "b"],
        pred=["a", "a"],
        classes=["a", "b"],
    )
    metrics = per_class_metrics(cm, classes=["a", "b"])
    assert metrics["b"].precision == 0.0
    assert metrics["b"].recall == 0.0
    assert metrics["b"].f1 == 0.0
    assert metrics["b"].support == 1


def test_per_class_metrics_error_counts_as_fn():
    """error 预测对真实类是 FN，不影响别人的 FP/TP。"""
    cm = confusion_matrix(
        true=["a", "a", "b"],
        pred=["a", ERROR_LABEL, "b"],
        classes=["a", "b"],
    )
    metrics = per_class_metrics(cm, classes=["a", "b"])
    # class a: TP=1, FP=0, FN=1 → P=1.0, R=0.5
    assert metrics["a"].precision == 1.0
    assert metrics["a"].recall == 0.5
    # class b: TP=1, FP=0, FN=0
    assert metrics["b"].precision == 1.0
    assert metrics["b"].recall == 1.0


def test_macro_f1():
    cm = confusion_matrix(
        true=["a", "a", "b", "b"],
        pred=["a", "b", "b", "b"],
        classes=["a", "b"],
    )
    metrics = per_class_metrics(cm, classes=["a", "b"])
    # a: P=1.0, R=0.5, F1=0.667
    # b: P=2/3, R=1.0, F1=0.8
    # macro = (0.667 + 0.8) / 2 ≈ 0.733
    assert macro_f1(metrics) == pytest.approx((2 / 3 + 0.8) / 2)


def test_compute_level_metrics_integration():
    """端到端：从原始 true/pred 列表算出完整 LevelMetrics。"""
    lm = compute_level_metrics(
        true_labels=["a", "a", "b", "b", "c"],
        pred_labels=["a", "b", "b", "a", "c"],
        classes=["a", "b", "c"],
    )
    assert lm.n == 5
    assert lm.accuracy == pytest.approx(3 / 5)
    assert "a" in lm.per_class
    assert lm.confusion["a"]["a"] == 1
    # macro_f1 端到端接线：等于对 per_class 单独算的 macro
    assert lm.macro_f1 == pytest.approx(macro_f1(lm.per_class))
