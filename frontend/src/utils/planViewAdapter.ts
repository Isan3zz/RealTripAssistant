import type { PlanView, PlanViewSegment } from '@/types'
import type { ParsedPlanMessage, PlanCategoryView } from './planParser'

const TYPE_LABELS: Record<string, string> = {
  transport: '路程',
  activity: '游玩',
  meal: '用餐',
  accommodation: '住宿',
}

export function planViewToParsedPlan(plan: PlanView): ParsedPlanMessage {
  return {
    title: plan.title || '行程规划完成',
    summary: Array.isArray(plan.summary) ? plan.summary : [],
    days: plan.days.map((day) => ({
      title: `第${day.day_number}天｜${day.title || '行程安排'}`,
      note: day.note || '',
      categories: segmentsToCategories(day.segments || []),
    })),
  }
}

function segmentsToCategories(segments: PlanViewSegment[]): PlanCategoryView[] {
  const categories: PlanCategoryView[] = []

  for (const segment of segments) {
    const name = TYPE_LABELS[segment.type] || '安排'
    let category = categories[categories.length - 1]
    if (!category || category.name !== name) {
      category = { name, segments: [] }
      categories.push(category)
    }
    category.segments.push({
      time: segment.time || [segment.start_time, segment.end_time].filter(Boolean).join('-'),
      title: segment.title,
      cost: formatCost(segment.estimated_cost?.amount),
      why: '',
      attention: segment.attention || '',
    })
  }

  return categories
}

function formatCost(amount?: number): string {
  if (!amount) return ''
  return `¥${amount.toLocaleString('zh-CN')}`
}
