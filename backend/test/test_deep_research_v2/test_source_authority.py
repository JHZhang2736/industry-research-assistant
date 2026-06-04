from app.config.source_authority import score_domain


def test_gov_tld_high_score():
    assert score_domain("https://www.stats.gov.cn/sj/zxfb/202402/t20240228.html") == 0.97
    # 未具名的 .gov.cn 走 TLD 规则
    assert score_domain("http://some-bureau.gov.cn/notice") == 0.95


def test_edu_tld():
    assert score_domain("https://www.tsinghua.edu.cn/page") == 0.9


def test_named_authoritative_domain():
    assert score_domain("https://www.xinhuanet.com/fortune/x.htm") == 0.95
    assert score_domain("https://www.caixin.com/2024/a.html") == 0.85


def test_self_media_low_score():
    assert score_domain("https://mp.weixin.qq.com/s/abc") == 0.4
    assert score_domain("https://zhuanlan.zhihu.com/p/123") == 0.45


def test_subdomain_and_www_stripped():
    # 子域命中母域规则
    assert score_domain("https://finance.people.com.cn/n1/x.html") == 0.95


def test_unknown_returns_none():
    assert score_domain("https://random-blog-xyz.com/post") is None


def test_blank_or_garbage_returns_none():
    assert score_domain("") is None
    assert score_domain("not a url") is None
