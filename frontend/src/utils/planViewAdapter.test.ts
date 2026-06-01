import { describe, expect, it } from 'vitest'

import type { PlanView } from '@/types'
import { planViewToParsedPlan } from './planViewAdapter'

describe('planViewToParsedPlan', () => {
  it('converts plan.v1 into the right-panel display model', () => {
    const plan: PlanView = {
      schema_version: 'plan.v1',
      title: '杭州至厦门3日游',
      origin: '杭州',
      destination: '厦门',
      day_count: 3,
      budget: { amount: 5000, currency: 'CNY' },
      total_cost: { amount: 520, currency: 'CNY' },
      summary: ['杭州 → 厦门', '3天'],
      days: [
        {
          day_number: 1,
          title: '抵达厦门',
          note: '轻松开始',
          segments: [
            {
              segment_id: 'seg_train',
              type: 'transport',
              module: 'morning',
              start_time: '08:00',
              end_time: '12:00',
              time: '08:00-12:00',
              title: '高铁前往厦门',
              location: null,
              estimated_cost: { amount: 420, currency: 'CNY' },
              tags: [],
              note: '',
              why: '减少折腾',
              attention: '提前取票',
            },
            {
              segment_id: 'seg_food',
              type: 'meal',
              module: 'afternoon',
              start_time: '12:30',
              end_time: '13:30',
              time: '12:30-13:30',
              title: '午餐',
              location: null,
              estimated_cost: { amount: 100, currency: 'CNY' },
              tags: [],
              note: '这是一条内部补充',
              why: '',
              attention: '',
            },
          ],
        },
      ],
    }

    const parsed = planViewToParsedPlan(plan)

    expect(parsed.title).toBe('杭州至厦门3日游')
    expect(parsed.summary).toEqual(['杭州 → 厦门', '3天'])
    expect(parsed.days[0].title).toBe('第1天｜抵达厦门')
    expect(parsed.days[0].categories.map((item) => item.name)).toEqual(['路程', '用餐'])
    expect(parsed.days[0].categories[0].segments[0]).toMatchObject({
      time: '08:00-12:00',
      title: '高铁前往厦门',
      cost: '¥420',
      why: '',
      attention: '提前取票',
    })
    expect(parsed.days[0].categories[1].segments[0]).toMatchObject({
      title: '午餐',
      why: '',
      attention: '',
    })
  })
})
