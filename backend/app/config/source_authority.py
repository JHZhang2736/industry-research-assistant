"""
信源域名权威度表 + 打分。

为 DeepScout 的可信度闸门提供「客观锚点」：相比 LLM 主观打分，
域名/TLD 是确定性信号。命中返回 0-1 基准分，未命中返回 None（交回 LLM 分）。

表以中文权威源为主（博查中文搜索的实际命中域名）。需要扩充时
直接往 DOMAIN_SCORES 加条目即可，无需改打分逻辑。
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

# 具名域名基准分（母域写法，子域自动命中）。score ∈ [0,1]
DOMAIN_SCORES = {
    # —— 官方 / 统计 ——
    "stats.gov.cn": 0.97,      # 国家统计局
    "pbc.gov.cn": 0.96,        # 中国人民银行
    "mof.gov.cn": 0.96,        # 财政部
    "ndrc.gov.cn": 0.95,       # 发改委
    # —— 央媒 / 权威媒体 ——
    "xinhuanet.com": 0.95,     # 新华网
    "people.com.cn": 0.95,     # 人民网
    "cctv.com": 0.85,          # 央视
    "chinanews.com.cn": 0.85,  # 中新网
    "ce.cn": 0.85,             # 中国经济网
    # —— 财经权威 ——
    "caixin.com": 0.85,        # 财新
    "yicai.com": 0.82,         # 第一财经
    "cnstock.com": 0.8,        # 中国证券网
    "stcn.com": 0.8,           # 证券时报
    "cs.com.cn": 0.8,          # 中证网
    "21jingji.com": 0.8,       # 21 世纪经济报道
    # —— 研究 / 咨询 ——
    "iresearch.com.cn": 0.78,  # 艾瑞咨询
    "gartner.com": 0.9,
    "mckinsey.com": 0.85,
    "statista.com": 0.8,
    # —— 一般科技媒体 ——
    "jiemian.com": 0.7,        # 界面新闻
    "36kr.com": 0.6,
    "huxiu.com": 0.6,
    # —— 自媒体 / 社区（低）——
    "mp.weixin.qq.com": 0.4,   # 公众号
    "baijiahao.baidu.com": 0.4,
    "zhihu.com": 0.45,
    "zhuanlan.zhihu.com": 0.45,
    "xueqiu.com": 0.5,
}

# TLD 后缀规则（确定性、零维护）。按列表顺序优先匹配。
TLD_RULES = [
    (".gov.cn", 0.95),
    (".gov", 0.95),
    (".edu.cn", 0.9),
    (".edu", 0.9),
]


def score_domain(url: str) -> Optional[float]:
    """根据 URL 域名返回客观权威基准分；无法判定返回 None。

    匹配优先级：具名域名（最长后缀优先）> TLD 规则 > None。
    """
    if not url or not isinstance(url, str):
        return None
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return None
    if not host:
        return None
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]

    # 具名域名：精确或子域命中，取最长匹配（finance.people.com.cn -> people.com.cn）
    best_score: Optional[float] = None
    best_len = -1
    for dom, sc in DOMAIN_SCORES.items():
        if host == dom or host.endswith("." + dom):
            if len(dom) > best_len:
                best_score = sc
                best_len = len(dom)
    if best_score is not None:
        return best_score

    # TLD 规则
    for suffix, sc in TLD_RULES:
        if host.endswith(suffix):
            return sc

    return None
