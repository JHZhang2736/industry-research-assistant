

"""
DeepResearch V2.0 - Agents 模块

导出所有专家Agent
"""

from .base import BaseAgent, AgentRegistry
from .architect import ChiefArchitect
from .scout import DeepScout
from .wizard import CodeWizard
from .critic import CriticMaster
from .writer import LeadWriter
from .data_analyst import DataAnalyst
from .planner import Planner
from .replanner import Replanner

__all__ = [
    'BaseAgent',
    'AgentRegistry',
    'ChiefArchitect',
    'DeepScout',
    'CodeWizard',
    'CriticMaster',
    'LeadWriter',
    'DataAnalyst',
    'Planner',
    'Replanner'
]
