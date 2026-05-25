

"""
DeepResearch V2.0 - LangGraph 工作流

实现多智能体协作的状态机图：
Plan -> Research -> Analyze -> Write -> Review -> (Revise) -> Complete

使用 LangGraph 实现循环和条件分支。
"""

import logging
import asyncio
from typing import Dict, Any, List, Literal, AsyncGenerator, Optional
from datetime import datetime

# 导入取消检查函数
try:
    from router.research_router import is_research_cancelled, clear_cancel_flag
except ImportError:
    try:
        from app.router.research_router import is_research_cancelled, clear_cancel_flag
    except ImportError:
        # 兼容直接运行脚本的情况
        def is_research_cancelled(session_id: str) -> bool:
            return False
        def clear_cancel_flag(session_id: str):
            pass

from langgraph.graph import StateGraph, END

from .state import ResearchState, ResearchPhase, create_initial_state
from .agents import ChiefArchitect, DeepScout, CodeWizard, CriticMaster, LeadWriter, DataAnalyst

# 导入检查点服务
try:
    from service.checkpoint_service import get_checkpoint_service
except ImportError:
    try:
        from app.service.checkpoint_service import get_checkpoint_service
    except ImportError:
        # 兼容直接运行脚本的情况
        def get_checkpoint_service():
            return None

# 导入配置
try:
    from config.llm_config import get_config
except ImportError:
    try:
        from app.config.llm_config import get_config
    except ImportError:
        # 兼容直接运行脚本的情况
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from config.llm_config import get_config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("DeepResearchGraph")


class DeepResearchGraph:
    """
    DeepResearch V2.0 工作流图

    实现完整的多智能体协作流程：
    1. Plan (ChiefArchitect) - 分析问题，生成研究大纲
    2. Research (DeepScout) - 并行深度搜索
    3. Analyze (CodeWizard) - 数据分析和可视化
    4. Write (LeadWriter) - 撰写报告
    5. Review (CriticMaster) - 对抗式审核
    6. Revise (LeadWriter) - 修订（如果需要）
    """

    def __init__(
        self,
        llm_api_key: str = None,
        llm_base_url: str = None,
        search_api_key: str = None,
        model: str = None,
        max_iterations: int = None
    ):
        """
        初始化工作流

        所有参数都可从配置文件读取，传入的参数会覆盖配置
        """
        # 获取配置
        config = get_config()

        # 使用传入参数或配置默认值
        self.llm_api_key = llm_api_key or config.api_key
        self.llm_base_url = llm_base_url or config.base_url
        self.search_api_key = search_api_key or config.search_api_key
        self.model = model or config.default_model
        self.max_iterations = max_iterations or config.research.max_iterations

        # 初始化各个 Agent（使用各自配置的模型）
        self.architect = ChiefArchitect(
            self.llm_api_key, self.llm_base_url,
            config.agents.architect.model
        )
        self.scout = DeepScout(
            self.llm_api_key, self.llm_base_url, self.search_api_key,
            config.agents.scout.model
        )
        self.data_analyst = DataAnalyst(
            self.llm_api_key, self.llm_base_url,
            config.agents.data_analyst.model
        )
        self.wizard = CodeWizard(
            self.llm_api_key, self.llm_base_url,
            config.agents.wizard.model
        )
        self.critic = CriticMaster(
            self.llm_api_key, self.llm_base_url,
            config.agents.critic.model
        )
        self.writer = LeadWriter(
            self.llm_api_key, self.llm_base_url,
            config.agents.writer.model
        )

        logger.info(f"DeepResearchGraph initialized with models:")
        logger.info(f"  - Architect: {config.agents.architect.model}")
        logger.info(f"  - Scout: {config.agents.scout.model}")
        logger.info(f"  - DataAnalyst: {config.agents.data_analyst.model}")
        logger.info(f"  - Wizard: {config.agents.wizard.model}")
        logger.info(f"  - Critic: {config.agents.critic.model}")
        logger.info(f"  - Writer: {config.agents.writer.model}")

        # 检查点服务
        self.checkpoint_service = get_checkpoint_service()

        # 构建图
        self.graph = self._build_langgraph()

    def _save_checkpoint(
        self,
        state: Dict[str, Any],
        user_id: str = None,
        ui_state: Dict[str, Any] = None
    ) -> bool:
        """保存检查点（包含后端状态和 UI 状态）"""
        if not self.checkpoint_service:
            return False

        session_id = state.get("session_id", "")
        if not session_id:
            return False

        try:
            checkpoint_id = self.checkpoint_service.save_checkpoint(
                session_id=session_id,
                state=state,
                user_id=user_id,
                ui_state=ui_state,
                final_report=state.get("final_report")
            )
            if checkpoint_id:
                logger.info(f"Checkpoint saved: {checkpoint_id}")
                return True
        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {e}")

        return False

    def _load_checkpoint(self, session_id: str) -> Dict[str, Any]:
        """加载检查点"""
        if not self.checkpoint_service:
            return None

        try:
            state = self.checkpoint_service.load_checkpoint(session_id)
            if state:
                logger.info(f"Checkpoint loaded for session: {session_id}")
                return state
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")

        return None

    def get_checkpoint_info(self, session_id: str) -> Dict[str, Any]:
        """获取检查点信息"""
        if not self.checkpoint_service:
            return None
        return self.checkpoint_service.get_checkpoint_info(session_id)

    def _build_langgraph(self):
        """
        构建 LangGraph 状态图

        拓扑：

            plan -> research -> analyze_data -> analyze_wizard -> write -> review
            review ─┬─ (COMPLETED 或 iteration >= max) ─> END
                    ├─ RE_RESEARCHING ─> re_research -> rewrite -> review
                    └─ REVISING       ─> revise -> review
        """
        workflow = StateGraph(ResearchState)

        # 节点：每个节点对应一个 agent 调用（或 phase 切换）
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("research", self._research_node)
        workflow.add_node("analyze_data", self._analyze_data_node)
        workflow.add_node("analyze_wizard", self._analyze_wizard_node)
        workflow.add_node("write", self._write_node)
        workflow.add_node("review", self._review_node)
        workflow.add_node("revise", self._revise_node)
        workflow.add_node("re_research", self._re_research_node)
        workflow.add_node("rewrite", self._rewrite_node)

        # 入口
        workflow.set_entry_point("plan")

        # 线性主干
        workflow.add_edge("plan", "research")
        workflow.add_edge("research", "analyze_data")
        workflow.add_edge("analyze_data", "analyze_wizard")
        workflow.add_edge("analyze_wizard", "write")
        workflow.add_edge("write", "review")

        # 三路条件边
        workflow.add_conditional_edges(
            "review",
            self._route_after_review,
            {
                "complete": END,
                "re_research": "re_research",
                "revise": "revise",
            }
        )

        # 循环回边
        workflow.add_edge("re_research", "rewrite")
        workflow.add_edge("rewrite", "review")
        workflow.add_edge("revise", "review")

        return workflow.compile()

    def _maybe_cancel(self, state: ResearchState) -> None:
        """
        在每个节点入口调用：检查 Redis 取消标志，命中则抛 CancelledError。

        LangGraph 会捕获 CancelledError 并终止 astream，外层包装捕获后发 research_cancelled 事件。
        """
        session_id = state.get("session_id", "")
        if session_id and is_research_cancelled(session_id):
            logger.info(f"Cancelled at node entry: session={session_id}")
            raise asyncio.CancelledError(f"research_cancelled:{session_id}")

    def _emit_phase_start(self, phase_key: str, content: str) -> None:
        """在节点入口推送 phase 开始事件（custom stream）

        与 _run_with_langgraph 末尾从 updates 流推的 phase 完成事件配对，
        让前端能看到「开始 X」→ 「X 完成」两次状态切换。
        """
        try:
            from langgraph.config import get_stream_writer
            writer = get_stream_writer()
            writer({"type": "phase", "phase": phase_key, "content": content})
        except (ImportError, RuntimeError, KeyError):
            # 不在 graph 上下文（如 run_sync 测试），静默忽略
            pass

    async def _plan_node(self, state: ResearchState) -> Dict[str, Any]:
        """规划节点（phase 设为 INIT 以触发 architect._initial_planning 的 phase==INIT 守卫）"""
        self._maybe_cancel(state)
        self._emit_phase_start("planning", "开始规划研究...")
        logger.info("Executing Plan node...")
        state = dict(state)
        state["phase"] = ResearchPhase.INIT.value
        result = await self.architect.process(state)
        return dict(result)

    async def _research_node(self, state: ResearchState) -> Dict[str, Any]:
        """初次研究节点"""
        self._maybe_cancel(state)
        self._emit_phase_start("researching", "开始深度搜索...")
        logger.info("Executing Research node...")
        state = dict(state)
        state["phase"] = ResearchPhase.RESEARCHING.value
        result = await self.scout.process(state)
        return dict(result)

    async def _analyze_data_node(self, state: ResearchState) -> Dict[str, Any]:
        """数据分析节点（DataAnalyst）"""
        self._maybe_cancel(state)
        self._emit_phase_start("analyzing", "开始数据分析...")
        logger.info("Executing AnalyzeData node...")
        state = dict(state)
        state["phase"] = ResearchPhase.ANALYZING.value
        result = await self.data_analyst.process(state)
        return dict(result)

    async def _analyze_wizard_node(self, state: ResearchState) -> Dict[str, Any]:
        """代码分析节点（CodeWizard，画图）"""
        self._maybe_cancel(state)
        self._emit_phase_start("analyzing", "开始生成图表...")
        logger.info("Executing AnalyzeWizard node...")
        state = dict(state)
        state["phase"] = ResearchPhase.ANALYZING.value
        result = await self.wizard.process(state)
        return dict(result)

    async def _write_node(self, state: ResearchState) -> Dict[str, Any]:
        """写作节点"""
        self._maybe_cancel(state)
        self._emit_phase_start("writing", "开始撰写报告...")
        logger.info("Executing Write node...")
        state = dict(state)
        state["phase"] = ResearchPhase.WRITING.value
        result = await self.writer.process(state)
        return dict(result)

    async def _review_node(self, state: ResearchState) -> Dict[str, Any]:
        """审核节点"""
        self._maybe_cancel(state)
        self._emit_phase_start("reviewing", "开始审核...")
        logger.info("Executing Review node...")
        state = dict(state)
        state["phase"] = ResearchPhase.REVIEWING.value
        result = await self.critic.process(state)
        return dict(result)

    async def _revise_node(self, state: ResearchState) -> Dict[str, Any]:
        """修订节点（仅文字修订）"""
        self._maybe_cancel(state)
        self._emit_phase_start("revising", "开始修订...")
        logger.info("Executing Revise node...")
        state = dict(state)
        state["phase"] = ResearchPhase.REVISING.value
        result = await self.writer.process(state)
        return dict(result)

    async def _re_research_node(self, state: ResearchState) -> Dict[str, Any]:
        """补充搜索节点（审核要求补料）

        注：scout._supplementary_research 在结束时会把 phase 设为 WRITING（遗留副作用）。
        紧接其后的 _rewrite_node 会再次设 WRITING，所以当前可正常工作；
        但若 scout 不再设 phase，需要本节点显式设 phase 为 WRITING 以便下游 writer 守卫通过。
        """
        self._maybe_cancel(state)
        self._emit_phase_start("re_researching", "开始补充搜索...")
        logger.info("Executing ReResearch node...")
        state = dict(state)
        state["phase"] = ResearchPhase.RE_RESEARCHING.value
        result = await self.scout.process(state)
        return dict(result)

    async def _rewrite_node(self, state: ResearchState) -> Dict[str, Any]:
        """补料后重写节点"""
        self._maybe_cancel(state)
        self._emit_phase_start("writing", "开始基于新信息重写...")
        logger.info("Executing Rewrite node...")
        state = dict(state)
        state["phase"] = ResearchPhase.WRITING.value
        result = await self.writer.process(state)
        return dict(result)

    def _route_after_review(
        self, state: ResearchState
    ) -> Literal["complete", "re_research", "revise"]:
        """
        审核后的三路路由：

        - iteration 已经用完 -> 直接 complete
        - critic 把 phase 设为 COMPLETED -> complete
        - critic 把 phase 设为 RE_RESEARCHING -> re_research（接 rewrite）
        - critic 把 phase 设为 REVISING -> revise
        - 其他兜底 -> complete
        """
        if state.get("iteration", 0) >= state.get("max_iterations", 3):
            logger.info(f"[route] iteration cap reached -> complete")
            return "complete"

        phase = state.get("phase", "")
        if phase == ResearchPhase.COMPLETED.value:
            return "complete"
        if phase == ResearchPhase.RE_RESEARCHING.value:
            return "re_research"
        if phase == ResearchPhase.REVISING.value:
            return "revise"

        logger.warning(f"[route] unexpected phase '{phase}' -> complete (fallback)")
        return "complete"

    async def run(
        self,
        query: str,
        session_id: str,
        resume: bool = False,
        user_id: str = None,
        search_web: bool = True,
        search_local: bool = False
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        执行研究流程（流式输出）

        Args:
            query: 用户问题
            session_id: 会话ID
            resume: 是否从检查点恢复
            user_id: 用户ID（用于检查点）
            search_web: 是否启用网络搜索（默认True）
            search_local: 是否启用本地知识库搜索（默认False）

        Yields:
            SSE 事件字典
        """
        # 尝试从检查点恢复
        state = None
        if resume and session_id:
            state = self._load_checkpoint(session_id)
            if state:
                yield {
                    "type": "research_resumed",
                    "phase": state.get("phase", ""),
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat()
                }

        # 如果没有检查点，创建初始状态
        if not state:
            state = create_initial_state(
                query, session_id,
                search_web=search_web,
                search_local=search_local
            )
            state["max_iterations"] = self.max_iterations

            yield {
                "type": "research_start",
                "query": query,
                "session_id": session_id,
                "search_web": search_web,
                "search_local": search_local,
                "timestamp": datetime.now().isoformat()
            }

        # 存储 user_id 用于检查点
        state["_user_id"] = user_id

        async for event in self._run_with_langgraph(state):
            yield event

    async def _run_with_langgraph(
        self, state: ResearchState
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        使用 LangGraph astream 执行（stream_mode=["custom","updates"]）

        - custom：agent 内部通过 get_stream_writer() 推的事件，直接 yield 给前端
        - updates：每个节点完成后的状态 diff，用于触发检查点保存 + phase 切换通知
        """
        user_id = state.get("_user_id")
        session_id = state.get("session_id", "")

        # 清除之前的取消标志，避免上次任务的残留标志立即触发本次取消
        if session_id:
            clear_cancel_flag(session_id)

        # 节点名 -> phase 事件 内容（用于 updates 流中合成"开始 X"消息）
        # 注意：节点真正"开始"的事件在节点函数内通过 stream_writer 推，
        # 这里 updates 流是"节点完成"的回报，用于检查点+完成统计。
        node_to_phase_info = {
            "plan": ("planning", "规划完成"),
            "research": ("researching", "深度搜索完成"),
            "analyze_data": ("analyzing", "数据分析完成"),
            "analyze_wizard": ("analyzing", "图表生成完成"),
            "write": ("writing", "初稿完成"),
            "review": ("reviewing", "审核完成"),
            "revise": ("revising", "修订完成"),
            "re_research": ("re_researching", "补充搜索完成"),
            "rewrite": ("rewriting", "重写完成"),
        }

        # UI 状态：前端恢复时需要的研究步骤、搜索结果、图表、知识图谱、流式报告
        ui_state = {
            "research_steps": [],
            "search_results": [],
            "charts": [],
            "knowledge_graph": None,
            "streaming_report": "",
        }

        last_state: Dict[str, Any] = dict(state)

        try:
            async for mode, chunk in self.graph.astream(
                state,
                stream_mode=["custom", "updates"],
            ):
                if mode == "custom":
                    # agent 内部 stream_writer 推的事件，直接转发
                    yield chunk
                    continue

                if mode == "updates":
                    # chunk 形如 {node_name: state_diff}
                    for node_name, node_diff in chunk.items():
                        if not isinstance(node_diff, dict):
                            continue
                        # 合并 diff 到 last_state 以便检查点保存看到完整状态
                        last_state.update(node_diff)

                        phase_key, phase_msg = node_to_phase_info.get(
                            node_name, (node_name, f"{node_name} 完成")
                        )

                        # 发 phase 事件
                        yield {
                            "type": "phase",
                            "phase": phase_key,
                            "content": phase_msg,
                        }

                        # 触发检查点保存（落 PG，含完整后端状态 + UI 状态）
                        cp_event = self._build_checkpoint_event(
                            last_state, user_id, ui_state, node_name
                        )
                        if cp_event:
                            yield cp_event

        except asyncio.CancelledError as e:
            logger.info(f"LangGraph execution cancelled: {e}")
            if self.checkpoint_service and session_id:
                try:
                    self.checkpoint_service.update_status(session_id, "cancelled")
                except Exception as e:
                    logger.debug(f"update_status(cancelled) failed (non-fatal): {e}")
            yield {"type": "research_cancelled", "message": "研究已取消"}
            return

        except Exception as e:
            logger.error(f"LangGraph execution error: {e}", exc_info=True)
            if self.checkpoint_service and session_id:
                try:
                    self.checkpoint_service.update_status(session_id, "failed", str(e))
                except Exception as e:
                    logger.debug(f"update_status(failed) failed (non-fatal): {e}")
            yield {"type": "error", "content": str(e)}
            return

        # 完成事件：发给前端展示研究结果摘要（final_report、quality_score、统计、references）
        if self.checkpoint_service and session_id:
            try:
                self.checkpoint_service.update_status(session_id, "completed")
            except Exception as e:
                logger.debug(f"update_status(completed) failed (non-fatal): {e}")

        yield self._build_completion_event(last_state)

    def _build_ui_references(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """将 state.references + facts 转换为前端友好的引用列表"""
        facts = state.get("facts", [])
        raw_refs = state.get("references", [])
        ui_refs = []
        for idx, ref in enumerate(raw_refs):
            fact = next(
                (f for f in facts if f.get("source_url") == ref.get("url")), None
            )
            title = ref.get("source") or ref.get("marker") or ""
            if not title and fact:
                content = fact.get("content", "")
                title = content[:50] + "..." if len(content) > 50 else content
            if not title:
                title = f"来源 {idx + 1}"
            ui_refs.append({
                "id": ref.get("id", idx + 1),
                "title": title,
                "link": ref.get("url", ""),
                "content": fact.get("content", "")[:200] if fact else "",
                "source": "web",
            })
        return ui_refs

    def _build_checkpoint_event(
        self,
        state: Dict[str, Any],
        user_id: Optional[str],
        ui_state: Dict[str, Any],
        node_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        节点完成后保存检查点 + 同步 UI 状态。

        与旧的 save_checkpoint_async + update_ui_state 等价，
        但作为同步方法被 astream 主循环驱动。
        """
        session_id = state.get("session_id", "")
        if not self.checkpoint_service or not session_id:
            return None

        # 同步 UI 状态字段
        new_charts = state.get("charts", [])
        if new_charts:
            ui_state["charts"] = new_charts

        new_report = state.get("final_report", "")
        if new_report:
            ui_state["streaming_report"] = new_report

        new_kg = state.get("knowledge_graph", {})
        if new_kg and (new_kg.get("nodes") or new_kg.get("edges")):
            ui_state["knowledge_graph"] = new_kg
        elif not ui_state.get("knowledge_graph"):
            ui_state["knowledge_graph"] = {"nodes": [], "edges": []}

        facts = state.get("facts", [])
        if facts:
            search_results_for_ui = []
            for fact in facts:
                source_name = fact.get("source_name", "")
                content = fact.get("content", "")
                title = source_name if source_name else (
                    content[:50] + "..." if len(content) > 50 else content
                )
                search_results_for_ui.append({
                    "id": fact.get("id", ""),
                    "title": title,
                    "source": fact.get("source_type", "web"),
                    "url": fact.get("source_url", ""),
                    "snippet": content[:200] if content else "",
                    "date": fact.get("timestamp", ""),
                })
            ui_state["search_results"] = search_results_for_ui

        # references 的 UI 转换
        ui_state["references"] = self._build_ui_references(state)

        # 节点 -> 步骤类型
        step_type_map = {
            "plan": "planning",
            "research": "researching",
            "analyze_data": "analyzing",
            "analyze_wizard": "analyzing",
            "write": "writing",
            "review": "reviewing",
            "revise": "revising",
            "re_research": "re_researching",
            "rewrite": "writing",
        }
        step_type = step_type_map.get(node_name, node_name)

        # 节点 -> stats（旧实现里按 phase 收集的统计字段）
        if step_type == "planning":
            stats = {"sections": len(state.get("outline", []))}
        elif step_type == "researching":
            stats = {
                "facts": len(state.get("facts", [])),
                "sources": len(state.get("references", [])),
            }
        elif step_type == "analyzing":
            stats = {"charts": len(state.get("charts", []))}
        elif step_type == "writing":
            stats = {"report_length": len(state.get("final_report", ""))}
        else:
            stats = {}

        step_info = {"type": step_type, "status": "completed", "stats": stats}

        existing = next(
            (s for s in ui_state["research_steps"] if s.get("type") == step_type),
            None,
        )
        if existing:
            existing.update(step_info)
        else:
            ui_state["research_steps"].append(step_info)

        if self._save_checkpoint(state, user_id, ui_state):
            return {
                "type": "checkpoint_saved",
                "phase": state.get("phase", ""),
                "session_id": session_id,
            }
        return None

    def _build_completion_event(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """组装 research_complete 事件，含 final_report、统计字段、前端友好的 references"""
        facts = state.get("facts", [])
        ui_refs = self._build_ui_references(state)

        return {
            "type": "research_complete",
            "final_report": state.get("final_report", ""),
            "quality_score": state.get("quality_score", 0.0),
            "facts_count": len(facts),
            "charts_count": len(state.get("charts", [])),
            "iterations": state.get("iteration", 0),
            "references": ui_refs,
        }

    async def run_sync(self, query: str, session_id: str) -> ResearchState:
        """
        同步执行（返回最终状态）

        用于不需要流式输出的场景
        """
        state = create_initial_state(query, session_id)
        state["max_iterations"] = self.max_iterations

        # 依次执行各阶段
        state = await self.architect.process(state)
        state = await self.scout.process(state)
        state = await self.data_analyst.process(state)
        state = await self.wizard.process(state)
        state = await self.writer.process(state)

        # 审核修订循环（支持智能路由）
        while state["iteration"] < state["max_iterations"]:
            state = await self.critic.process(state)

            if state["phase"] == ResearchPhase.COMPLETED.value:
                break

            # 智能路由：需要补充搜索
            if state["phase"] == ResearchPhase.RE_RESEARCHING.value:
                state = await self.scout.process(state)
                state["phase"] = ResearchPhase.WRITING.value
                state = await self.writer.process(state)

            # 仅需要文字修订
            elif state["phase"] == ResearchPhase.REVISING.value:
                state = await self.writer.process(state)
            else:
                break

        return state


def create_research_graph(
    llm_api_key: str = None,
    llm_base_url: str = None,
    search_api_key: str = None,
    model: str = None
) -> DeepResearchGraph:
    """
    工厂函数：创建 DeepResearch 工作流图

    所有参数都是可选的，会从配置文件读取默认值

    Args:
        llm_api_key: LLM API 密钥（可选，默认从配置读取）
        llm_base_url: LLM API 基础 URL（可选，默认从配置读取）
        search_api_key: 搜索 API 密钥（可选，默认从配置读取）
        model: 默认模型名称（可选，默认从配置读取）

    Returns:
        DeepResearchGraph 实例
    """
    return DeepResearchGraph(
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        search_api_key=search_api_key,
        model=model
    )
