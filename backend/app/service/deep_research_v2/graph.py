

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
    from app.router.research_router import is_research_cancelled, clear_cancel_flag
except (ImportError, SyntaxError):
    try:
        from router.research_router import is_research_cancelled, clear_cancel_flag
    except (ImportError, SyntaxError):
        # 兼容直接运行脚本的情况
        def is_research_cancelled(session_id: str) -> bool:
            return False
        def clear_cancel_flag(session_id: str):
            pass

from langgraph.graph import StateGraph, END

from .state import ResearchState, ResearchPhase, create_initial_state
from .agents import (
    DeepScout, CodeWizard, CriticMaster, LeadWriter, DataAnalyst,
    Planner, Replanner,
)
from .executor import executor_node

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


# ============================================================================
# 模块级路由函数（v3 Plan-and-Execute）
# ============================================================================

MAX_REPLAN = 3
QUALITY_PASS_THRESHOLD = 7.0  # critic 给分 < 该值即视为"未通过"，需 replan


def route_after_critic(state: ResearchState) -> str:
    """critic node 之后的路由

    替换原 "只看 suggested_actions" 的过松逻辑——critic LLM 经常打低分但忘填
    actions，那种情况也应该 replan。新规则：

    - 已达 MAX_REPLAN → END（兜底，防死循环）
    - verdict == "pass" → END（即使有 actions 也信任 critic 的 pass 判断）
    - 满足任一即视为"需要 replan"：
        * suggested_actions 非空
        * unresolved_issues > 0
        * quality_score < 阈值
        * verdict 不是 "pass"
    """
    replan_count = state.get("replan_count", 0)
    if replan_count >= MAX_REPLAN:
        return "END"

    verdict = (state.get("verdict") or "").lower()
    if verdict == "pass":
        return "END"

    suggested = state.get("suggested_actions", []) or []
    unresolved = state.get("unresolved_issues", 0) or 0
    score = float(state.get("quality_score", 0.0) or 0.0)

    if suggested or unresolved > 0 or score < QUALITY_PASS_THRESHOLD or verdict in ("needs_revision", "needs_re_research"):
        return "replanner"
    return "END"


def route_after_replanner(state: ResearchState) -> str:
    """replanner 之后路由：预留 fallback 接口（本期恒 False）"""
    if state.get("replan_count", 0) >= MAX_REPLAN:
        return "END"
    # 预留 ReAct fallback 分支：本期 fallback_triggered 恒 False
    # TODO(phase-2): 实现 supervisor_fallback node
    if state.get("fallback_triggered", False):
        return "supervisor_fallback"
    return "executor"


class DeepResearchGraph:
    """
    DeepResearch V3.0 工作流图（Plan-and-Execute supervisor）

    4-node 主图：
    1. Planner: 生成大纲 + plan（含 parallel_group）
    2. Executor: 调度 @tool 完成 search / analyze / charts / write
    3. Critic: 审核 + 输出 suggested_actions
    4. Replanner: 规则驱动把 suggested_actions 翻译成补救 plan
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
        # planner / replanner 共用 architect 配置项（保留命名以兼容现有 llm_config）
        self.planner = Planner(
            self.llm_api_key, self.llm_base_url,
            config.agents.architect.model
        )
        self.replanner = Replanner(
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
        logger.info(f"  - Planner/Replanner: {config.agents.architect.model}")
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
        """构建 v3 Plan-and-Execute 主图

        拓扑：

            planner → executor → critic
                                   ├── pass → END
                                   └── needs_revision → replanner
                                                          ├── max_replan → END
                                                          ├── (TODO) fallback
                                                          └── default → executor
        """
        workflow = StateGraph(ResearchState)

        # 4 个主 node
        workflow.add_node("planner", self._planner_node)
        workflow.add_node("executor", executor_node)
        workflow.add_node("critic", self._critic_node)
        workflow.add_node("replanner", self._replanner_node)

        workflow.set_entry_point("planner")

        # 顺序边
        workflow.add_edge("planner", "executor")
        workflow.add_edge("executor", "critic")

        # critic 之后的条件路由
        workflow.add_conditional_edges(
            "critic",
            route_after_critic,
            {"END": END, "replanner": "replanner"},
        )

        # replanner 之后的条件路由
        workflow.add_conditional_edges(
            "replanner",
            route_after_replanner,
            {
                "END": END,
                "executor": "executor",
                # TODO(phase-2): "supervisor_fallback": "supervisor_fallback"
            },
        )

        return workflow.compile()

    def _maybe_cancel(self, state: ResearchState) -> None:
        """在每个节点入口调用：检查 Redis 取消标志，命中则抛 CancelledError。"""
        session_id = state.get("session_id", "")
        if session_id and is_research_cancelled(session_id):
            logger.info(f"Cancelled at node entry: session={session_id}")
            raise asyncio.CancelledError(f"research_cancelled:{session_id}")

    def _emit_phase_start(self, phase_key: str, content: str) -> None:
        """在节点入口推送 phase 开始事件（custom stream）"""
        try:
            from langgraph.config import get_stream_writer
            writer = get_stream_writer()
            writer({"type": "phase", "phase": phase_key, "content": content})
        except (ImportError, RuntimeError, KeyError):
            pass

    def _emit_event(self, event_type: str, content: Dict[str, Any]) -> None:
        """通用 custom stream 事件推送（前端 SSE 直接消费）

        前端的 "研究详情" 面板由 research_step / outline / search_results /
        knowledge_graph / charts 等具名事件驱动。tool 内部 helper 已经会推
        content 类事件，这里只补发节点级的 step 容器创建事件。
        """
        try:
            from langgraph.config import get_stream_writer
            writer = get_stream_writer()
            writer({"type": event_type, "content": content})
        except (ImportError, RuntimeError, KeyError):
            pass

    async def _planner_node(self, state: ResearchState) -> Dict[str, Any]:
        """planner node 包装：调用 self.planner.process()"""
        self._maybe_cancel(state)
        self._emit_phase_start("planning", "开始规划研究...")
        logger.info("Executing Planner node...")
        result = await self.planner.process(state)

        # 兼容前端：补发 outline 和 research_step:planning，让侧边栏建立 planning 详情
        outline = result.get("outline", []) if isinstance(result, dict) else []
        self._emit_event("outline", {
            "outline": outline,
            "research_questions": [],
        })
        self._emit_event("research_step", {
            "step_type": "planning",
            "title": "📋 规划研究大纲",
            "subtitle": f"生成 {len(outline)} 个章节",
            "status": "completed",
            "stats": {"sections_count": len(outline)},
        })
        return result

    async def _critic_node(self, state: ResearchState) -> Dict[str, Any]:
        """critic node 包装"""
        self._maybe_cancel(state)
        self._emit_phase_start("reviewing", "开始审核...")
        logger.info("Executing Critic node...")
        # 在 critic 真正运行前先建一个 reviewing 详情容器
        self._emit_event("research_step", {
            "step_type": "reviewing",
            "title": "🔎 审核报告",
            "subtitle": "",
            "status": "running",
        })
        result = await self.critic.process(state)
        # 完成态：把 quality_score / unresolved 写入 stats（前端忽略未知字段）
        if isinstance(result, dict):
            quality = result.get("quality_score", 0.0)
            unresolved = result.get("unresolved_issues", 0)
        else:
            quality, unresolved = 0.0, 0
        self._emit_event("research_step", {
            "step_type": "reviewing",
            "title": "🔎 审核报告",
            "status": "completed",
            "stats": {
                "quality_score": quality,
                "unresolved_issues": unresolved,
            },
        })
        return result

    async def _replanner_node(self, state: ResearchState) -> Dict[str, Any]:
        """replanner node 包装：把 suggested_actions 翻译成补救 plan

        兜底逻辑：critic LLM 给低分但忘填 actions 时，从 critic_feedback 推导，
        或退而对所有 section 做 retry_search，避免"判定需 replan 却无事可做"。
        """
        self._maybe_cancel(state)
        self._emit_phase_start("replanning", "开始重规划...")
        logger.info("Executing Replanner node...")

        suggested = list(state.get("suggested_actions", []) or [])

        if not suggested:
            feedback = state.get("critic_feedback", []) or []
            derived: List[str] = []
            for fb in feedback:
                target = fb.get("target_section", "") if isinstance(fb, dict) else ""
                issue = fb.get("issue_type", "") if isinstance(fb, dict) else ""
                if not target or target in ("全局", "global", ""):
                    continue
                if issue in ("missing_source", "outdated", "incomplete"):
                    derived.append(f"retry_search:{target}")
                elif issue in ("logic_error", "bias", "hallucination"):
                    derived.append(f"rewrite:{target}")
                else:
                    derived.append(f"retry_search:{target}")
            if derived:
                suggested = list(dict.fromkeys(derived))  # 去重保序
            else:
                outline = state.get("outline", []) or []
                suggested = [
                    f"retry_search:{s.get('id')}"
                    for s in outline if s.get("id")
                ]
            logger.info(f"Replanner fallback actions ({len(suggested)}): {suggested}")

        result = await self.replanner.process(state, suggested_actions=suggested)
        return result


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

        # 节点名 -> phase 事件 内容（用于 updates 流中合成"X 完成"消息）
        # 注意：节点真正"开始"的事件在节点函数内通过 stream_writer 推，
        # 这里 updates 流是"节点完成"的回报，用于检查点+完成统计。
        # v3 Plan-and-Execute 4 个主 node。executor 内部完成 search/analyze/charts/write，
        # 因此 executor 完成事件 phase 选 "executing"（前端把它映射成研究中状态）。
        node_to_phase_info = {
            "planner": ("planning", "规划完成"),
            "executor": ("executing", "执行批次完成"),
            "critic": ("reviewing", "审核完成"),
            "replanner": ("replanning", "重规划完成"),
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

        query = state.get("query", "")
        trace_config = {
            "run_name": f"research: {query[:40]}" if query else "research",
            "metadata": {"session_id": session_id, "query": query},
            "tags": ["deep_research_v3"] + ([session_id] if session_id else []),
        }

        try:
            async for mode, chunk in self.graph.astream(
                state,
                config=trace_config,
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

        # 节点 -> 步骤类型（v3 4-node 主图）
        # executor 内部包含 search/analyze/charts/write，stats 时按内容字段量分支
        step_type_map = {
            "planner": "planning",
            "executor": "executing",
            "critic": "reviewing",
            "replanner": "replanning",
        }
        step_type = step_type_map.get(node_name, node_name)

        # 节点 -> stats
        if step_type == "planning":
            stats = {"sections": len(state.get("outline", []))}
        elif step_type == "executing":
            stats = {
                "facts": len(state.get("facts", [])),
                "sources": len(state.get("references", [])),
                "charts": len(state.get("charts", [])),
                "sections_drafted": len(state.get("draft_sections", {})),
            }
        elif step_type == "reviewing":
            stats = {
                "quality_score": state.get("quality_score", 0.0),
                "unresolved_issues": state.get("unresolved_issues", 0),
            }
        elif step_type == "replanning":
            stats = {
                "replan_count": state.get("replan_count", 0),
                "plan_steps": len(state.get("plan", [])),
            }
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
            "iterations": state.get("replan_count", 0),
            "references": ui_refs,
        }

    async def run_sync(self, query: str, session_id: str) -> ResearchState:
        """
        同步执行（返回最终状态）

        用于不需要流式输出的场景。v3 直接走主图 ainvoke。
        """
        state = create_initial_state(query, session_id)
        state["max_iterations"] = self.max_iterations
        final_state = await self.graph.ainvoke(state)
        return final_state


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
