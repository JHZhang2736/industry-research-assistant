

import IconBg from '@/assets/index/bg.png'
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
    color: '#055588',
    bgColor: '#E7F4FF',
  },
  {
    id: 'competitive_research',
    title: '竞品研究',
    desc: '产品对比、技术差异、市场份额',
    prompt: '请对 [公司A] 和 [公司B] 做对比分析，包括产品、技术、市场份额。',
    color: '#1144BA',
    bgColor: '#EFF3FF',
  },
  {
    id: 'policy_interpretation',
    title: '政策解读',
    desc: '政策核心、影响范围、企业应对',
    prompt: '请解读 [政策名称] 的核心内容、影响范围和企业应对方向。',
    color: '#335519',
    bgColor: '#EDF7E6',
  },
  {
    id: 'tech_survey',
    title: '技术调研',
    desc: '技术现状、主流方案、演进方向',
    prompt: '请调研 [技术领域] 的发展现状、主流方案、技术演进方向。',
    color: '#B85C00',
    bgColor: '#FFF4E6',
  },
]

export default function Index() {
  const navigate = useNavigate()
  const [searchKeyword, setSearchKeyword] = useState('')

  const cardList = useMemo(
    () =>
      RESEARCH_TEMPLATES.map((t) => ({
        id: t.id,
        title: t.title,
        icon: IconSearch,
        desc: t.desc,
        color: t.color,
        bgColor: t.bgColor,
        prompt: t.prompt,
      })),
    [],
  )

  const filteredCardList = useMemo(() => {
    if (!searchKeyword.trim()) return cardList
    const keyword = searchKeyword.toLowerCase()
    return cardList.filter(
      (item) =>
        item.title.toLowerCase().includes(keyword) ||
        item.desc.toLowerCase().includes(keyword),
    )
  }, [cardList, searchKeyword])

  const handleCardClick = (prompt: string) => {
    navigate(`/chat?prompt=${encodeURIComponent(prompt)}`)
  }

  return (
    <div className={styles['index-page']}>
      <div className={styles.header}>
        <img className={styles.bg} src={IconBg} />
        <div className={styles.title}>Hi～欢迎使用 AI 深度研究助手</div>
        <div className={styles.desc}>
          多 Agent 协同 + Critic 自反思，自动产出结构化研究报告
        </div>
      </div>

      <div className={styles['search-bar']}>
        <div className={styles['switch']}>
          <div className={styles.active}>研究模板</div>
        </div>

        <div className={styles['search-bar__input']}>
          <Input
            prefix={<img src={IconSearch} />}
            placeholder="搜索研究模板"
            size="large"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            allowClear
          />
        </div>
      </div>

      <div className={styles['card-list']}>
        {filteredCardList.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: '#999', width: '100%' }}>
            未找到匹配的研究模板
          </div>
        ) : (
          filteredCardList.map((item) => (
            <div
              className={styles['card-item']}
              key={item.id}
              style={{
                backgroundColor: item.bgColor,
                color: item.color,
                cursor: 'pointer',
              }}
              onClick={() => handleCardClick(item.prompt)}
            >
              <div
                className={styles['card-item__icon']}
                style={{ borderColor: item.color }}
              >
                <img src={item.icon} />
              </div>
              <div className={styles['card-item__title']}>{item.title}</div>
              <div className={styles['card-item__desc']}>{item.desc}</div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
