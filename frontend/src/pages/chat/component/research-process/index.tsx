

import { CheckOutlined, LoadingOutlined } from '@ant-design/icons'
import classNames from 'classnames'
import styles from './index.module.scss'

// 与 research-detail 的 ResearchStep 对齐，覆盖 v3 全部步骤类型
export type ResearchStepType =
  | 'scoping'
  | 'planning'
  | 'approval'
  | 'searching'
  | 'analyzing'
  | 'generating'
  | 'executing'
  | 'writing'
  | 'reviewing'
  | 'replanning'
  | 're_researching'
  | 'revising'

export interface ResearchStep {
  id: string
  type: ResearchStepType
  title: string
  subtitle?: string
  status: 'pending' | 'running' | 'completed'
  stats?: {
    resultsCount?: number
    chartsCount?: number
    entitiesCount?: number
    sectionsCount?: number
    wordCount?: number
    questionsCount?: number
    sourcesCount?: number
    referencesCount?: number
  }
}

interface ResearchProcessProps {
  steps: ResearchStep[]
  selectedStepId?: string
  onStepClick?: (stepId: string) => void
}

// 步骤类型 -> 中文标签，恢复检查点时 title 可能是原始 type，用它兜底
const stepLabels: Record<ResearchStepType, string> = {
  scoping: '主题勘察',
  approval: '确认大纲',
  planning: '研究计划',
  searching: '信息检索',
  analyzing: '数据分析',
  generating: '内容生成',
  executing: '研究执行',
  writing: '撰写报告',
  reviewing: '质量审核',
  replanning: '重新规划',
  re_researching: '补充搜索',
  revising: '内容修订',
}

export default function ResearchProcess({ steps, selectedStepId, onStepClick }: ResearchProcessProps) {
  if (!steps.length) return null

  return (
    <div className={styles.process}>
      <div className={styles.header}>研究流程</div>
      <div className={styles.timeline}>
        {steps.map((step, index) => {
          const isSelected = step.id === selectedStepId
          const isLast = index === steps.length - 1

          return (
            <div
              key={step.id}
              className={classNames(styles.step, {
                [styles.selected]: isSelected,
                [styles.clickable]: step.status === 'completed' && (step.stats?.resultsCount || step.stats?.chartsCount),
              })}
              onClick={() => {
                if (step.status === 'completed' && onStepClick) {
                  onStepClick(step.id)
                }
              }}
            >
              {/* 连接线 */}
              {!isLast && (
                <div className={classNames(styles.line, {
                  [styles.completed]: step.status === 'completed'
                })} />
              )}

              {/* 图标 */}
              <div className={classNames(styles.icon, styles[step.status])}>
                {step.status === 'completed' ? (
                  <CheckOutlined />
                ) : step.status === 'running' ? (
                  <LoadingOutlined spin />
                ) : (
                  <span className={styles.dot} />
                )}
              </div>

              {/* 内容 */}
              <div className={styles.content}>
                <div className={styles.title}>
                  {stepLabels[step.type] || step.title}
                  {step.status === 'running' && <span className={styles.runningDot} />}
                </div>
                {step.subtitle ? <div className={styles.subtitle}>{step.subtitle}</div> : null}

                {/* 统计标签 */}
                {step.stats && step.status === 'completed' && (
                  <div className={styles.tags}>
                    {step.stats.sectionsCount ? (
                      <span className={styles.tag}>{step.stats.sectionsCount} 个章节</span>
                    ) : null}
                    {step.stats.resultsCount ? (
                      <span className={styles.tag}>{step.stats.resultsCount} 条结果</span>
                    ) : null}
                    {step.stats.sourcesCount ? (
                      <span className={styles.tag}>{step.stats.sourcesCount} 个来源</span>
                    ) : null}
                    {step.stats.chartsCount ? (
                      <span className={classNames(styles.tag, styles.chartTag)}>{step.stats.chartsCount} 个图表</span>
                    ) : null}
                    {step.stats.entitiesCount ? (
                      <span className={styles.tag}>{step.stats.entitiesCount} 个实体</span>
                    ) : null}
                    {step.stats.wordCount ? (
                      <span className={styles.tag}>{step.stats.wordCount} 字</span>
                    ) : null}
                  </div>
                )}
              </div>

              {/* 箭头 */}
              {(step.status === 'completed' && (step.stats?.resultsCount || step.stats?.chartsCount)) && (
                <div className={styles.arrow}>
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                    <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
