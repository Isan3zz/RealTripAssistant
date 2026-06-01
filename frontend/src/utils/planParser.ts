export interface PlanSegmentView {
  time: string
  title: string
  cost: string
  why: string
  attention: string
}

export interface PlanCategoryView {
  name: string
  segments: PlanSegmentView[]
}

export interface PlanDayView {
  title: string
  note: string
  categories: PlanCategoryView[]
}

export interface ParsedPlanMessage {
  title: string
  summary: string[]
  days: PlanDayView[]
}

const TITLE_RE = /^[✅✔]\s*/
const SUMMARY_RE = /^(📍|💰|节奏[：:])/
const DAY_RE = /^(?:📅|📮)\s*Day\s+\d+\s*[—-]\s*.+$/i
const CATEGORY_RE = /^[—-]{2,}\s*(.+?)\s*[—-]{2,}$/
const WHY_RE = /^为什么推荐[：:]/
const ATTENTION_RE = /^注意事项[：:]/
const SEGMENT_RE = /^([\d:]{4,5}-[\d:]{4,5})\s+(.+)$/
const COST_RE = /\s([¥￥]\s?[\d,]+(?:\.\d+)?)$/

export function parsePlanMessage(content: string): ParsedPlanMessage {
  const result: ParsedPlanMessage = {
    title: '行程规划完成',
    summary: [],
    days: [],
  }
  let currentDay: PlanDayView | null = null
  let currentCategory: PlanCategoryView | null = null
  let currentSegment: PlanSegmentView | null = null

  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line) continue

    if (TITLE_RE.test(line)) {
      result.title = line.replace(TITLE_RE, '').replace(/[！!]$/, '').trim() || result.title
      continue
    }

    if (SUMMARY_RE.test(line)) {
      result.summary.push(line)
      continue
    }

    if (DAY_RE.test(line)) {
      currentDay = { title: line, note: '', categories: [] }
      result.days.push(currentDay)
      currentCategory = null
      currentSegment = null
      continue
    }

    if (!currentDay) continue

    const categoryMatch = line.match(CATEGORY_RE)
    if (categoryMatch) {
      currentCategory = {
        name: categoryMatch[1].trim(),
        segments: [],
      }
      currentDay.categories.push(currentCategory)
      currentSegment = null
      continue
    }

    if (WHY_RE.test(line)) {
      if (currentSegment) currentSegment.why = line.replace(WHY_RE, '').trim()
      continue
    }

    if (ATTENTION_RE.test(line)) {
      if (currentSegment) currentSegment.attention = line.replace(ATTENTION_RE, '').trim()
      continue
    }

    const segmentMatch = line.match(SEGMENT_RE)
    if (segmentMatch) {
      if (!currentCategory) {
        currentCategory = { name: '安排', segments: [] }
        currentDay.categories.push(currentCategory)
      }
      const parsed = splitCost(segmentMatch[2])
      currentSegment = {
        time: segmentMatch[1],
        title: parsed.title,
        cost: parsed.cost,
        why: '',
        attention: '',
      }
      currentCategory.segments.push(currentSegment)
      continue
    }

    if (!currentDay.note) {
      currentDay.note = line
    }
  }

  return result
}

function splitCost(value: string): { title: string; cost: string } {
  const match = value.match(COST_RE)
  if (!match || match.index == null) return { title: value, cost: '' }
  return {
    title: value.slice(0, match.index).trim(),
    cost: match[1].replace(/\s+/g, ''),
  }
}
