

"""
DeepResearch V2.0 - Agent 基类

所有专家Agent的基类，提供通用的LLM调用、日志记录等功能。
"""

import json
import logging
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from openai import OpenAI

try:
    from langsmith.wrappers import wrap_openai
except ImportError:  # langsmith 未装时退化为 no-op，保持原 client
    def wrap_openai(client):
        return client

from ..state import ResearchState, AgentLog
from ..concurrency import get_llm_semaphore

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')


class BaseAgent(ABC):
    """
    Agent 基类

    所有专家Agent继承此类，实现特定的 process 方法。
    """

    def __init__(
        self,
        name: str,
        role: str,
        llm_api_key: str,
        llm_base_url: str,
        model: str = "qwen-max"
    ):
        self.name = name
        self.role = role
        self.model = model
        # wrap_openai：LANGSMITH_TRACING=true 时自动把每次 chat.completions.create
        # 注册成 LangSmith span（含 prompt/completion/token usage）；
        # 未开启 tracing 时为零开销 passthrough。
        self.client = wrap_openai(OpenAI(api_key=llm_api_key, base_url=llm_base_url))
        self.logger = logging.getLogger(f"Agent.{name}")

    @abstractmethod
    async def process(self, state: ResearchState) -> ResearchState:
        """
        处理状态并返回更新后的状态

        Args:
            state: 当前研究状态

        Returns:
            更新后的状态
        """
        pass

    async def call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = True,
        temperature: float = 0.3,
        max_tokens: int = 16000,  # 拉满到最大值
        *,
        state: Optional["ResearchState"] = None,
        action: str = "llm_call",
    ) -> str:
        """
        调用 LLM

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            json_mode: 是否强制JSON输出
            temperature: 温度参数
            max_tokens: 最大token数
            state: 研究状态（如果提供，会自动把本次调用写入 state["logs"]）
            action: 本次调用的标识符（用于日志/成本统计）

        Returns:
            LLM 响应文本
        """
        start_time = time.time()

        # Inject current date banner so the LLM knows what "today" / "recent" / "latest"
        # means at runtime. Without this, models default to their training-data
        # snapshot (often 2024) and produce stale references / outdated framing.
        _today = datetime.now()
        date_banner = (
            f"# 当前日期\n"
            f"今天是 {_today:%Y 年 %m 月 %d 日}（{_today.year} 年）。"
            f'文中所有 "今年" / "近期" / "最新" / "当前" 等时间指称均以此日期为准。'
            f'不要默认 prompt 示例里的年份（如 2024）就是"当前年份"——示例只是格式样例。'
            f"\n\n"
        )
        system_prompt_with_date = date_banner + (system_prompt or "")

        try:
            kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt_with_date},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": temperature,
                "max_tokens": max_tokens
            }

            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            # Bound concurrent in-flight LLM calls per provider to stay under QPM
            sem = get_llm_semaphore(getattr(self.client, "base_url", "") or "")
            async with sem:
                response = await asyncio.to_thread(
                    self.client.chat.completions.create,
                    **kwargs
                )

            content = response.choices[0].message.content
            duration = int((time.time() - start_time) * 1000)

            self.logger.info(f"LLM call completed in {duration}ms, response length: {len(content)}")

            # Auto-log LLM call to state["logs"] for downstream eval/cost tracking
            if state is not None and "logs" in state:
                tokens_used = 0
                try:
                    usage = getattr(response, "usage", None)
                    if usage is not None:
                        tokens_used = int(getattr(usage, "total_tokens", 0) or 0)
                except Exception:
                    tokens_used = 0
                state["logs"].append({
                    "timestamp": datetime.now().isoformat(),
                    "agent": self.name,
                    "action": action,
                    "input_summary": (system_prompt or "")[:120],
                    "output_summary": (content or "")[:120],
                    "duration_ms": duration,
                    "tokens_used": tokens_used,
                    "model": self.model,
                })

            return content

        except Exception as e:
            self.logger.error(f"LLM call failed: {e}")
            raise

    def parse_json_response(self, response: str) -> Dict[str, Any]:
        """安全解析JSON响应，处理markdown代码块和格式问题"""
        import re

        def fix_escaped_newlines(s: str) -> str:
            """修复过度转义的换行符"""
            # 处理多层转义: \\\\n -> \n, \\n -> \n
            s = s.replace('\\\\\\\\n', '\n')
            s = s.replace('\\\\n', '\n')
            # 处理可能的 \\r\\n
            s = s.replace('\\\\\\\\r', '\r')
            s = s.replace('\\\\r', '\r')
            return s

        def try_parse(s: str) -> Optional[Dict]:
            """尝试解析JSON，包含修复逻辑"""
            # 清理常见问题
            s = s.strip()
            # 移除可能的BOM
            if s.startswith('\ufeff'):
                s = s[1:]

            try:
                result = json.loads(s)
                # 成功解析后，修复值中的转义字符
                return self._fix_escaped_values(result)
            except json.JSONDecodeError:
                pass

            # 尝试修复常见JSON问题
            try:
                # 修复无效的JSON转义序列 \[ \] \# 等 (LLM经常产生这种错误)
                # 需要在字符串值中修复，但避免影响已转义的反斜杠
                # \\[ 是有效的(表示 \[ 字面量)，但 \[ 不是有效的JSON转义
                s = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', '', s)
                # 移除注释
                s = re.sub(r'//.*?$', '', s, flags=re.MULTILINE)
                s = re.sub(r'/\*.*?\*/', '', s, flags=re.DOTALL)
                # 修复尾随逗号
                s = re.sub(r',(\s*[}\]])', r'\1', s)
                # 修复缺少逗号的情况（在 } 或 ] 后面缺少逗号）
                s = re.sub(r'([}\]])(\s*)([{\[])', r'\1,\2\3', s)
                # 修复没有引号的key
                s = re.sub(r'(\{|\,)\s*(\w+)\s*:', r'\1"\2":', s)
                result = json.loads(s)
                return self._fix_escaped_values(result)
            except json.JSONDecodeError:
                pass

            return None

        # 1. 先尝试直接解析
        result = try_parse(response)
        if result:
            self.logger.debug("Direct JSON parse succeeded")
            return result

        # 2. 尝试提取markdown代码块
        code_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        match = re.search(code_block_pattern, response)
        if match:
            result = try_parse(match.group(1))
            if result:
                self.logger.debug("Extracted JSON from code block")
                return result

        # 3. 尝试找到最外层的 {...}
        start = response.find('{')
        end = response.rfind('}')
        if start != -1 and end != -1 and end > start:
            result = try_parse(response[start:end+1])
            if result:
                self.logger.debug("Extracted JSON from braces")
                return result

        # 4. 最后尝试用更宽松的方式解析
        try:
            # 使用 ast.literal_eval 作为备选
            import ast
            # 将 true/false/null 转换为 Python 格式
            s = response
            s = re.sub(r'\btrue\b', 'True', s)
            s = re.sub(r'\bfalse\b', 'False', s)
            s = re.sub(r'\bnull\b', 'None', s)
            start = s.find('{')
            end = s.rfind('}')
            if start != -1 and end != -1:
                result = ast.literal_eval(s[start:end+1])
                if isinstance(result, dict):
                    self.logger.debug("Parsed using ast.literal_eval")
                    return result
        except:
            pass

        self.logger.error(f"JSON parse error, could not extract valid JSON")
        self.logger.warning(f"Raw response (first 800 chars): {response[:800]}")
        return {}

    def _fix_escaped_values(self, obj: Any, key: str = None) -> Any:
        """
        递归修复字典和列表中的转义字符

        注意：对于 'code' 字段，不处理转义，因为代码中的 \n 是有意义的转义序列
        """
        if isinstance(obj, dict):
            return {k: self._fix_escaped_values(v, key=k) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._fix_escaped_values(item, key=key) for item in obj]
        elif isinstance(obj, str):
            # 对于代码字段，不进行转义处理
            # 因为代码中的 \n 应该保持为 \n（两个字符），而不是真正的换行
            if key in ('code', 'fixed_code', 'revised_content'):
                return obj

            # 对于其他字段，修复过度转义的换行符
            result = obj
            result = result.replace('\\\\n', '\n')
            result = result.replace('\\n', '\n')
            result = result.replace('\\\\r', '\r')
            result = result.replace('\\r', '\r')
            result = result.replace('\\\\t', '\t')
            result = result.replace('\\t', '\t')
            return result
        else:
            return obj

    def add_message(self, state: ResearchState, event_type: str, content: Any) -> None:
        """添加消息到状态（用于SSE流式输出）

        在 LangGraph 节点上下文中通过 get_stream_writer() 推 custom 事件；
        无论是否在上下文中，都会追加到 state["messages"] 以保留事件历史。

        Args:
            state: 研究状态
            event_type: 事件类型
            content: 消息内容
        """
        from langgraph.config import get_stream_writer

        message = {
            "type": event_type,
            "agent": self.name,
            "timestamp": datetime.now().isoformat(),
            "content": content
        }
        state["messages"].append(message)

        try:
            writer = get_stream_writer()
            writer(message)
        except (RuntimeError, KeyError):
            # 不在 graph 执行上下文中（如 run_sync 或单元测试）
            self.logger.debug(f"No stream writer in context, event recorded only: {event_type}")

    def add_log(
        self,
        state: ResearchState,
        action: str,
        input_summary: str,
        output_summary: str,
        duration_ms: int,
        tokens_used: int = 0
    ) -> None:
        """添加执行日志"""
        log = {
            "timestamp": datetime.now().isoformat(),
            "agent": self.name,
            "action": action,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "duration_ms": duration_ms,
            "tokens_used": tokens_used
        }
        state["logs"].append(log)


class AgentRegistry:
    """Agent 注册表"""

    _agents: Dict[str, BaseAgent] = {}

    @classmethod
    def register(cls, agent: BaseAgent) -> None:
        """注册Agent"""
        cls._agents[agent.name] = agent

    @classmethod
    def get(cls, name: str) -> Optional[BaseAgent]:
        """获取Agent"""
        return cls._agents.get(name)

    @classmethod
    def all(cls) -> Dict[str, BaseAgent]:
        """获取所有Agent"""
        return cls._agents.copy()
