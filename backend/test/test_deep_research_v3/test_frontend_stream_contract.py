from pathlib import Path


def test_continue_stream_handles_codewizard_chart_event():
    """The outline-continue SSE reader must consume CodeWizard's singular chart event."""
    repo_root = Path(__file__).resolve().parents[3]
    chat_page = repo_root / "frontend" / "src" / "pages" / "chat" / "index.tsx"
    source = chat_page.read_text(encoding="utf-8")

    start = source.index("const continueApprovedOutline")
    end = source.index("const send = useCallback", start)
    continue_handler = source[start:end]

    assert "json.type === 'chart'" in continue_handler
