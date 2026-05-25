

"""
DeepResearch V2.0 - 生成式多智能体协作网络

核心特点：
1. 6 个专家 Agent 协作：ChiefArchitect / DeepScout / DataAnalyst / CodeWizard / CriticMaster / LeadWriter
2. 动态状态机：Plan -> Research -> Analyze -> Write -> Review -> Revise
3. 对抗式质检：CriticMaster 确保报告质量
4. 代码解释器：CodeWizard 支持 Python 数据分析和可视化
5. LangGraph 实现：支持循环和条件分支

使用方式：
```python
from service.deep_research_v2.service import DeepResearchV2Service

service = DeepResearchV2Service()
async for event in service.research("中国AI芯片市场分析"):
    print(event)
```
"""

from .state import (
    ResearchState,
    ResearchPhase,
    Section,
    Fact,
    DataPoint,
    Chart,
    CriticFeedback,
    create_initial_state
)

from .graph import DeepResearchGraph, create_research_graph

from .agents import (
    ChiefArchitect,
    DeepScout,
    DataAnalyst,
    CodeWizard,
    CriticMaster,
    LeadWriter
)

__all__ = [
    'ResearchState',
    'ResearchPhase',
    'Section',
    'Fact',
    'DataPoint',
    'Chart',
    'CriticFeedback',
    'create_initial_state',
    'DeepResearchGraph',
    'create_research_graph',
    'ChiefArchitect',
    'DeepScout',
    'DataAnalyst',
    'CodeWizard',
    'CriticMaster',
    'LeadWriter',
]
