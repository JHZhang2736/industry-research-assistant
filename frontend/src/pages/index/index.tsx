import IconSearch from '@/assets/index/search.svg'
import { Input } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import styles from './index.module.scss'

// 研究模板：按研究方法论维度（市场 / 竞品 / 政策 / 技术），与具体行业解耦
const RESEARCH_TEMPLATES = [
  {
    id: 'market_analysis',
    title: '市场分析',
    desc: '市场规模、增长趋势、主要参与者',
    prompt: '请帮我分析 [行业/产品] 的市场规模、增长趋势和主要参与者。',
    emoji: '📈',
    tone: 'var(--acc)',
    soft: '#eef3ff',
  },
  {
    id: 'competitive_research',
    title: '竞品研究',
    desc: '产品对比、技术差异、市场份额',
    prompt: '请对 [公司A] 和 [公司B] 做对比分析，包括产品、技术、市场份额。',
    emoji: '⚔️',
    tone: 'var(--ok)',
    soft: '#eafaf0',
  },
  {
    id: 'policy_interpretation',
    title: '政策解读',
    desc: '政策核心、影响范围、企业应对',
    prompt: '请解读 [政策名称] 的核心内容、影响范围和企业应对方向。',
    emoji: '📜',
    tone: 'var(--warn)',
    soft: '#fff2e6',
  },
  {
    id: 'tech_survey',
    title: '技术调研',
    desc: '技术现状、主流方案、演进方向',
    prompt: '请调研 [技术领域] 的发展现状、主流方案、技术演进方向。',
    emoji: '🔬',
    tone: 'var(--magenta)',
    soft: '#fde8f3',
  },
]

export default function Index() {
  const navigate = useNavigate()
  const [searchKeyword, setSearchKeyword] = useState('')

  const filteredCardList = useMemo(() => {
    if (!searchKeyword.trim()) return RESEARCH_TEMPLATES
    const keyword = searchKeyword.toLowerCase()
    return RESEARCH_TEMPLATES.filter(
      (item) =>
        item.title.toLowerCase().includes(keyword) ||
        item.desc.toLowerCase().includes(keyword),
    )
  }, [searchKeyword])

  const handleCardClick = (prompt: string) => {
    navigate(`/chat?prompt=${encodeURIComponent(prompt)}`)
  }

  return (
    <div className={styles['index-page']}>
      <section className={styles.hero}>
        <div className={styles.tag}>
          <i />
          多 Agent 协同 · Critic 自反思
        </div>
        <h1 className={styles.title}>
          把复杂课题，
          <br />
          <span className={styles.hl}>交给会深度推演的 AI</span>
        </h1>
        <p className={styles.subtitle}>
          全自动深度检索 + 多专家协同，自动产出高置信度、可溯源的结构化研究报告。
        </p>

        <div className={styles.search}>
          <Input
            prefix={<img src={IconSearch} />}
            placeholder="搜索研究模板"
            size="large"
            variant="borderless"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            allowClear
          />
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h3>研究模板</h3>
        </div>

        <div className={styles.grid}>
          {filteredCardList.length === 0 ? (
            <div className={styles.empty}>未找到匹配的研究模板</div>
          ) : (
            filteredCardList.map((item) => (
              <div
                className={styles.tpl}
                key={item.id}
                onClick={() => handleCardClick(item.prompt)}
              >
                <div
                  className={styles.tplIcon}
                  style={{ background: item.soft, color: item.tone }}
                >
                  {item.emoji}
                </div>
                <div className={styles.tplTitle}>{item.title}</div>
                <div className={styles.tplDesc}>{item.desc}</div>
                <span className={styles.tplArrow}>↗</span>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  )
}
