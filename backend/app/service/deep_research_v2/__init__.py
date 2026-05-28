

"""
DeepResearch V3.0 - Plan-and-Execute supervisor

4-node 主图：planner → executor → critic → (replanner)* → END
- planner: 生成大纲 + plan（含 parallel_group）
- executor: 调度 @tool（search_section / analyze_facts / generate_charts / write_section）
- critic: 审核 + suggested_actions
- replanner: 规则驱动把 suggested_actions 翻译成补救 plan

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
    DeepScout,
    DataAnalyst,
    CodeWizard,
    CriticMaster,
    LeadWriter,
    Planner,
    Replanner,
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
    'DeepScout',
    'DataAnalyst',
    'CodeWizard',
    'CriticMaster',
    'LeadWriter',
    'Planner',
    'Replanner',
]
