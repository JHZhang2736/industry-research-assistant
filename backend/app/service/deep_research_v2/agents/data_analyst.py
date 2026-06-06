

"""
DeepResearch V2.0 - 数据分析师 Agent (DataAnalyst)

职责：
1. 从搜索结果中提取结构化数据
2. 生成可视化图表配置(ECharts)
3. 识别数据趋势和洞察
"""

import uuid
from typing import Dict, Any, List

from .base import BaseAgent
from ..state import ResearchState, ResearchPhase
from ..source_scoring import final_credibility

# data_point 最终可信度低于此值硬丢弃（与 scout.CREDIBILITY_FLOOR 一致）
CREDIBILITY_FLOOR = 0.3
# DataAnalyst 抽数取样上限（控制 token）
RAW_SOURCE_TOP_N = 12
RAW_SOURCE_TEXT_MAXLEN = 1500


def _norm_url(u: str) -> str:
    """归一化 url 用于匹配：去首尾空白、去尾部斜杠。容忍 LLM 回填时的轻微格式漂移。"""
    return (u or "").strip().rstrip("/")


class DataAnalyst(BaseAgent):
    """
    数据分析师 - 专注于数据提取和可视化

    特点：
    - 从文本中提取结构化数据点
    - 生成ECharts可视化配置
    - 识别趋势和洞察
    """

    # 数据提取 Prompt
    DATA_EXTRACTION_PROMPT = """你是专业的数据分析师，擅长从文本中提取结构化数据。

## 研究主题
{query}

## 搜索结果
{search_results}

## 任务
从以上搜索结果中提取所有可量化的数据点，包括：
1. 市场规模数据（金额、单位、年份）
2. 增长率数据（百分比、时间段）
3. 市场份额数据（企业/领域、占比）
4. 排名数据（企业、产品、技术）
5. 时间序列数据（同一指标在不同年份的值）

## 输出要求
请输出JSON格式：
```json
{{
    "data_points": [
        {{
            "id": "dp_001",
            "metric_key": "china_ai_market_size",
            "name": "中国AI市场规模",
            "value": 5000,
            "unit": "亿元",
            "year": 2024,
            "source_url": "https://www.gov.cn/xxx",
            "source": "艾瑞咨询",
            "category": "market_size",
            "confidence": 0.9
        }}
    ],
    "time_series": [
        {{
            "id": "ts_001",
            "metric": "AI市场规模",
            "unit": "亿元",
            "data": [
                {{"year": 2020, "value": 3200}},
                {{"year": 2021, "value": 4100}},
                {{"year": 2024, "value": 8500}}
            ],
            "source": "艾瑞咨询"
        }}
    ],
    "distributions": [
        {{
            "id": "dist_001",
            "name": "细分领域市场份额",
            "year": 2024,
            "data": [
                {{"category": "计算机视觉", "value": 32, "unit": "%"}},
                {{"category": "自然语言处理", "value": 28, "unit": "%"}}
            ],
            "source": "IDC"
        }}
    ],
    "insights": [
        "中国AI市场规模在2024年突破5000亿元",
        "计算机视觉是最大的细分领域，占比32%"
    ]
}}
```

注意：
- 只提取有明确来源的数据
- confidence表示数据可信度(0-1)
- metric_key 用英文 snake_case 表示同一指标的归一化键（如 "china_ai_market_size"），同一指标在不同来源/年份用相同 metric_key
- source_url 必须填该数据点所依据来源的 URL（从上方各 [来源N] 标注的 URL 中选）
- 如果没有找到相关数据，返回空数组"""

    # 图表生成 Prompt
    CHART_GENERATION_PROMPT = """你是数据可视化专家，擅长生成ECharts图表配置。

## 研究主题
{query}

## 可用数据
{data}

## 任务
根据数据生成合适的ECharts图表配置，选择最能展示数据特点的图表类型。

## 图表类型选择规则
- 时间序列数据 → line (折线图)
- 分类比较数据 → bar (柱状图)
- 占比分布数据 → pie (饼图)
- 进度/百分比 → horizontal_bar (横向进度条)
- 多维对比 → radar (雷达图)

## 设计要求
1. 配色使用简约专业色系：
   - 主色：#1677ff (蓝)
   - 辅助色：#52c41a (绿), #722ed1 (紫), #fa8c16 (橙), #eb2f96 (粉)
2. 标题简洁明了
3. 不要过多装饰，保持简约

## 输出要求
请输出JSON格式：
```json
{{
    "charts": [
        {{
            "id": "chart_001",
            "title": "中国AI市场规模",
            "subtitle": "2020-2024年市场规模（亿元）",
            "type": "line",
            "echarts_option": {{
                "grid": {{"left": "3%", "right": "4%", "bottom": "3%", "containLabel": true}},
                "xAxis": {{
                    "type": "category",
                    "data": ["2020", "2021", "2022", "2023", "2024"],
                    "axisLine": {{"lineStyle": {{"color": "#e8e8e8"}}}},
                    "axisLabel": {{"color": "#666"}}
                }},
                "yAxis": {{
                    "type": "value",
                    "axisLine": {{"show": false}},
                    "splitLine": {{"lineStyle": {{"color": "#f0f0f0"}}}}
                }},
                "series": [{{
                    "type": "line",
                    "data": [3200, 4100, 5200, 6800, 8500],
                    "smooth": true,
                    "symbol": "circle",
                    "symbolSize": 8,
                    "itemStyle": {{"color": "#1677ff"}},
                    "lineStyle": {{"width": 3}},
                    "areaStyle": {{"color": {{"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": [{{"offset": 0, "color": "rgba(22,119,255,0.2)"}}, {{"offset": 1, "color": "rgba(22,119,255,0)"}}]}}}}
                }}]
            }}
        }},
        {{
            "id": "chart_002",
            "title": "细分领域市场份额",
            "subtitle": "2024年各技术领域占比",
            "type": "horizontal_bar",
            "echarts_option": {{
                "grid": {{"left": "25%", "right": "15%", "top": "5%", "bottom": "5%"}},
                "xAxis": {{"type": "value", "show": false, "max": 100}},
                "yAxis": {{
                    "type": "category",
                    "data": ["计算机视觉", "自然语言处理", "机器学习平台", "智能语音", "其他"],
                    "axisLine": {{"show": false}},
                    "axisTick": {{"show": false}},
                    "axisLabel": {{"color": "#333", "fontSize": 13}}
                }},
                "series": [{{
                    "type": "bar",
                    "data": [
                        {{"value": 32, "itemStyle": {{"color": "#1677ff"}}}},
                        {{"value": 28, "itemStyle": {{"color": "#722ed1"}}}},
                        {{"value": 24, "itemStyle": {{"color": "#1677ff"}}}},
                        {{"value": 10, "itemStyle": {{"color": "#52c41a"}}}},
                        {{"value": 6, "itemStyle": {{"color": "#fa8c16"}}}}
                    ],
                    "barWidth": 12,
                    "label": {{
                        "show": true,
                        "position": "right",
                        "formatter": "{{c}}%",
                        "color": "#666"
                    }},
                    "backgroundStyle": {{"color": "#f5f5f5"}},
                    "showBackground": true
                }}]
            }}
        }}
    ]
}}
```"""

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = "qwen-max"):
        super().__init__(
            name="DataAnalyst",
            role="数据分析师",
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            model=model
        )

    async def process(self, state: ResearchState) -> ResearchState:
        """处理入口"""
        if state["phase"] == ResearchPhase.ANALYZING.value:
            return await self._analyze_data(state)
        return state

    async def _analyze_data(self, state: ResearchState) -> ResearchState:
        """执行数据分析"""
        self.logger.info("Starting data analysis...")

        # 发送开始事件
        self.add_message(state, "research_step", {
            "step_id": f"step_analyze_{uuid.uuid4().hex[:8]}",
            "step_type": "analyzing",
            "title": "数据分析",
            "subtitle": "生成可视化",
            "status": "running",
            "stats": {"results_count": 0, "charts_count": 0}
        })

        # 1. 提取结构化数据
        extracted_data = await self._extract_data(state)

        # 2. 生成可视化图表
        charts = await self._generate_charts(state, extracted_data)

        # 更新状态
        if charts:
            state["charts"].extend(charts)
            self.logger.info(f"[DataAnalyst] 生成了 {len(charts)} 个 ECharts 图表，准备发送 charts 事件")
            for i, chart in enumerate(charts):
                self.logger.info(f"[DataAnalyst] 图表 {i+1}: id={chart.get('id')}, title={chart.get('title')}, has_echarts_option={bool(chart.get('echarts_option'))}")
            # 发送图表事件
            self.add_message(state, "charts", {
                "charts": charts
            })
            self.logger.info(f"[DataAnalyst] ✅ charts 事件已发送")

        # 发送完成事件
        self.add_message(state, "research_step", {
            "step_type": "analyzing",
            "title": "数据分析",
            "subtitle": "生成可视化",
            "status": "completed",
            "stats": {
                "results_count": len(state.get("facts", [])),
                "charts_count": len(charts) if charts else 0
            }
        })

        return state

    async def _extract_data(self, state: ResearchState) -> Dict[str, Any]:
        """从 raw_sources（未压缩原文）提取结构化数据。DataAnalyst 是唯一抽数 owner。"""
        self.logger.info("Extracting structured data from raw_sources...")

        raw_sources = state.get("raw_sources", [])
        if not raw_sources:
            self.logger.info("No raw_sources to extract data from")
            return {"data_points": [], "time_series": [], "distributions": [], "insights": []}

        # 按 relevance 降序取 top-N，控制 token
        top = sorted(
            raw_sources, key=lambda s: s.get("relevance_score", 0.0), reverse=True
        )[:RAW_SOURCE_TOP_N]

        blocks = []
        url_meta = {}
        for i, s in enumerate(top):
            url = _norm_url(s.get("url", ""))
            url_meta[url] = {
                "date": s.get("date", ""),
                "name": s.get("site_name", ""),
                "related_sections": s.get("related_sections", []),
            }
            text = (s.get("text", "") or "")[:RAW_SOURCE_TEXT_MAXLEN]
            blocks.append(
                f"[来源{i+1}] {s.get('title', '')} | {s.get('site_name', '')} | {url}\n{text}"
            )

        prompt = self.DATA_EXTRACTION_PROMPT.format(
            query=state["query"],
            search_results="\n\n".join(blocks),
        )

        response = await self.call_llm(
            system_prompt="你是专业的数据分析师，擅长从原文中提取结构化数据。请输出JSON格式。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.2,
            state=state,
            action="extract_data",
        )
        result = self.parse_json_response(response)

        # data_points：重算可信度（硬丢弃）+ 超集 schema（含旧别名）
        kept = []
        for dp in result.get("data_points", []):
            source_url = _norm_url(dp.get("source_url", ""))
            meta = url_meta.get(source_url, {})
            if source_url and not meta:
                # source_url 不在本次提供的来源里（LLM 回填异常/可能臆造）——保留但告警，便于审计
                self.logger.warning(
                    f"[DataAnalyst] data_point source_url 不在 top 来源内: {source_url}"
                )
            cred = final_credibility(
                dp.get("confidence", dp.get("credibility", 0.5)),
                source_url,
                meta.get("date", ""),
            )
            if cred < CREDIBILITY_FLOOR:
                continue
            source_name = dp.get("source") or meta.get("name", "")
            entry = {
                "id": dp.get("id") or f"dp_{uuid.uuid4().hex[:8]}",
                "metric_key": dp.get("metric_key", ""),
                "name": dp.get("name", ""),
                "value": dp.get("value"),
                "unit": dp.get("unit", ""),
                "year": dp.get("year"),
                "source_url": source_url,
                "source_name": source_name,
                "credibility": cred,
                "related_sections": meta.get("related_sections", []),
                # 旧别名（下游 Critic/Writer/Wizard 兼容）
                "source": source_name,
                "confidence": cred,
            }
            state["data_points"].append(entry)
            kept.append(entry)

        # time_series / distributions：仅存（下游消费留待后续）
        state.setdefault("time_series", []).extend(result.get("time_series", []))
        state.setdefault("distributions", []).extend(result.get("distributions", []))

        if result.get("insights"):
            state["insights"].extend(result["insights"])

        self.logger.info(
            f"Extracted {len(kept)} data points (kept), "
            f"{len(result.get('time_series', []))} time_series, "
            f"{len(result.get('distributions', []))} distributions"
        )
        return {
            "data_points": kept,
            "time_series": result.get("time_series", []),
            "distributions": result.get("distributions", []),
            "insights": result.get("insights", []),
        }

    async def _generate_charts(self, state: ResearchState, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成可视化图表"""
        self.logger.info("[DataAnalyst] ========== 开始生成 ECharts 可视化图表 ==========")

        # 准备数据
        data_for_charts = {
            "data_points": extracted_data.get("data_points", []),
            "time_series": extracted_data.get("time_series", []),
            "distributions": extracted_data.get("distributions", []),
            "existing_data_points": state.get("data_points", [])[:10]
        }

        # 如果没有足够数据，跳过
        total_data = (len(data_for_charts["data_points"]) +
                     len(data_for_charts["time_series"]) +
                     len(data_for_charts["distributions"]))

        self.logger.info(f"[DataAnalyst] 图表数据统计: data_points={len(data_for_charts['data_points'])}, time_series={len(data_for_charts['time_series'])}, distributions={len(data_for_charts['distributions'])}, total={total_data}")

        if total_data == 0:
            self.logger.warning("[DataAnalyst] ⚠️ 没有足够数据生成图表，跳过")
            return []

        prompt = self.CHART_GENERATION_PROMPT.format(
            query=state["query"],
            data=str(data_for_charts)
        )

        response = await self.call_llm(
            system_prompt="你是数据可视化专家，擅长生成ECharts图表配置。请输出JSON格式。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.3,
            state=state,
            action="generate_charts",
        )

        result = self.parse_json_response(response)
        charts = result.get("charts", [])

        # 为每个图表添加唯一ID
        for chart in charts:
            if not chart.get("id"):
                chart["id"] = f"chart_{uuid.uuid4().hex[:8]}"

        self.logger.info(f"Generated {len(charts)} charts")

        return charts

    async def analyze_for_section(self, state: ResearchState, section_title: str) -> Dict[str, Any]:
        """为特定章节分析数据（可被其他Agent调用）"""
        self.logger.info(f"Analyzing data for section: {section_title}")

        # 收集与该章节相关的事实
        related_facts = [f for f in state.get("facts", [])
                        if section_title in str(f.get("related_sections", []))]

        if not related_facts:
            related_facts = state.get("facts", [])[:10]

        # 简化的数据提取
        search_results_text = [f"- {f.get('content', '')}" for f in related_facts]

        prompt = f"""分析以下内容，提取与"{section_title}"相关的关键数据：

{chr(10).join(search_results_text)}

输出JSON格式：
{{
    "key_metrics": [
        {{"name": "指标名", "value": "值", "unit": "单位"}}
    ],
    "trend": "上升/下降/稳定",
    "summary": "一句话总结"
}}"""

        response = await self.call_llm(
            system_prompt="你是数据分析师，提取关键数据。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.2,
            state=state,
            action="analyze_for_section",
        )

        return self.parse_json_response(response)

    async def extract_data_points(self, state: ResearchState) -> Dict[str, Any]:
        """v3 入口：从 state["raw_sources"] 提取 data_points/time_series/distributions/insights。

        复用 _extract_data（mutates state），用 snapshot/diff 捕获四类新增项返回。
        """
        if not state.get("raw_sources"):
            return {"data_points": [], "time_series": [], "distributions": [], "insights": []}

        dp_before = len(state.get("data_points", []))
        ts_before = len(state.get("time_series", []))
        dist_before = len(state.get("distributions", []))
        insights_before = len(state.get("insights", []))

        await self._extract_data(state)

        return {
            "data_points": state.get("data_points", [])[dp_before:],
            "time_series": state.get("time_series", [])[ts_before:],
            "distributions": state.get("distributions", [])[dist_before:],
            "insights": state.get("insights", [])[insights_before:],
        }
