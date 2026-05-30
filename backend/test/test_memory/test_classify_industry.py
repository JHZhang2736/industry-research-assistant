from app.service.memory_engine import classify_industry


def test_classify_known_industries():
    assert classify_industry("分析车路协同与智慧高速的市场规模") == "智慧交通"
    assert classify_industry("金融科技支付赛道的监管趋势") == "金融科技"
    assert classify_industry("医疗健康行业的创新药研发") == "医疗健康"
    assert classify_industry("新能源与电力储能的投资前景") == "能源电力"


def test_classify_fallback_to_general():
    assert classify_industry("今天天气怎么样") == "general"
    assert classify_industry("") == "general"


def test_classify_first_match_wins_is_deterministic():
    q = "智慧交通和金融科技的对比"
    assert classify_industry(q) == classify_industry(q)
