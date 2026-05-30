"""Confusion matrix + per-class P/R/F1 + macro F1 + overall accuracy。

设计：纯函数，不依赖外部 IO。所有除零情况返回 0.0 不抛异常，便于报表渲染。
"""
from app.intent_eval.types import PerClassMetrics, LevelMetrics, ERROR_LABEL


def accuracy(true_labels: list[str], pred_labels: list[str]) -> float:
    if not true_labels:
        return 0.0
    correct = sum(1 for t, p in zip(true_labels, pred_labels) if t == p)
    return correct / len(true_labels)


def confusion_matrix(
    true: list[str], pred: list[str], classes: list[str]
) -> dict[str, dict[str, int]]:
    """rows=true label, cols=pred label。预测列含 ERROR_LABEL 桶以容纳异常 case。"""
    cols = list(classes) + [ERROR_LABEL]
    cm = {t: {p: 0 for p in cols} for t in classes}
    for t, p in zip(true, pred):
        if t not in cm:
            continue
        if p in cm[t]:
            cm[t][p] += 1
        else:
            # pred 不在已知集合（不应发生，但兜底）
            cm[t][ERROR_LABEL] += 1
    return cm


def per_class_metrics(
    cm: dict[str, dict[str, int]], classes: list[str]
) -> dict[str, PerClassMetrics]:
    """从 confusion matrix 算 per-class P / R / F1 / support。

    Precision[c] = TP[c] / sum over true rows where pred=c
    Recall[c]    = TP[c] / sum of row c
    """
    out: dict[str, PerClassMetrics] = {}
    for c in classes:
        tp = cm.get(c, {}).get(c, 0)
        # FP = 所有真实类(≠c)预测为 c 的 → 跨行 cm[t][c] for t in classes if t != c
        fp = sum(cm.get(t, {}).get(c, 0) for t in classes if t != c)
        # FN = c 行除 c 列以外的所有列（含 ERROR_LABEL）
        fn = sum(v for col, v in cm.get(c, {}).items() if col != c)
        support = tp + fn
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        out[c] = PerClassMetrics(precision=precision, recall=recall, f1=f1, support=support)
    return out


def macro_f1(per_class: dict[str, PerClassMetrics]) -> float:
    if not per_class:
        return 0.0
    return sum(m.f1 for m in per_class.values()) / len(per_class)


def compute_level_metrics(
    true_labels: list[str], pred_labels: list[str], classes: list[str]
) -> LevelMetrics:
    cm = confusion_matrix(true_labels, pred_labels, classes)
    pc = per_class_metrics(cm, classes)
    return LevelMetrics(
        accuracy=accuracy(true_labels, pred_labels),
        macro_f1=macro_f1(pc),
        per_class=pc,
        confusion=cm,
        n=len(true_labels),
    )
