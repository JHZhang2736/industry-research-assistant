from app.service.context_compressor import ContextCompressor


def _msgs(n):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"消息{i} " * 50}
            for i in range(n)]


def test_below_threshold_no_compression():
    cc = ContextCompressor(keep_recent_turns=2, compress_threshold=10_000_000,
                           summarize_fn=lambda text: "SUMMARY")
    msgs = _msgs(6)
    history, summary, cursor = cc.build_history(prior_summary="", summarized_up_to=0, messages=msgs)
    assert "SUMMARY" not in history
    assert summary == ""
    assert cursor == 0
    assert "消息5" in history


def test_above_threshold_compresses_old_keeps_recent():
    cc = ContextCompressor(keep_recent_turns=2, compress_threshold=10,
                           summarize_fn=lambda text: "OLD_SUMMARY")
    msgs = _msgs(6)
    history, summary, cursor = cc.build_history(prior_summary="", summarized_up_to=0, messages=msgs)
    assert "OLD_SUMMARY" in history
    assert "消息4" in history and "消息5" in history
    assert summary == "OLD_SUMMARY"
    assert cursor == 4


def test_incremental_only_compresses_new_old_turns():
    captured = {}
    def fake_summarize(text):
        captured["text"] = text
        return "MERGED"
    cc = ContextCompressor(keep_recent_turns=2, compress_threshold=10,
                           summarize_fn=fake_summarize)
    msgs = _msgs(8)
    history, summary, cursor = cc.build_history(prior_summary="PREV", summarized_up_to=4, messages=msgs)
    assert "PREV" in captured["text"]
    assert "消息4" in captured["text"]
    assert "消息2" not in captured["text"]
    assert cursor == 6
    assert "消息6" in history and "消息7" in history


def test_summarize_failure_degrades_without_raising():
    def boom(text):
        raise RuntimeError("llm down")
    cc = ContextCompressor(keep_recent_turns=2, compress_threshold=10, summarize_fn=boom)
    msgs = _msgs(6)
    history, summary, cursor = cc.build_history(prior_summary="PREV", summarized_up_to=0, messages=msgs)
    assert "消息4" in history and "消息5" in history
    assert "PREV" in history
