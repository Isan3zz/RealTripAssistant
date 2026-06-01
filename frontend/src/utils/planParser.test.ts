import { describe, expect, it } from 'vitest'

import { parsePlanMessage } from './planParser'

describe('parsePlanMessage', () => {
  it('parses plan output that uses postbox day markers and ascii category dividers', () => {
    const content = `✅ 行程规划完成！

📍 杭州→厦门 3天
💰 预算 ¥5,000 | 总花费 ¥3,854
节奏：moderate

📮 Day 1 - 厦门初体验
   多云22-28°C，适合出游
  --- 路程 ---
   06:30-14:37 从杭州前往厦门北站 ¥400
      为什么推荐：尽量选省心路线。
      注意事项：预留换乘时间。
  --- 游玩 ---
   15:17-17:00 环岛路骑行 ¥50
      为什么推荐：适合作为当天核心安排。
      注意事项：遇到人多就缩短停留。`

    const parsed = parsePlanMessage(content)

    expect(parsed.title).toBe('行程规划完成')
    expect(parsed.summary).toEqual([
      '📍 杭州→厦门 3天',
      '💰 预算 ¥5,000 | 总花费 ¥3,854',
      '节奏：moderate',
    ])
    expect(parsed.days).toHaveLength(1)
    expect(parsed.days[0].title).toBe('📮 Day 1 - 厦门初体验')
    expect(parsed.days[0].categories.map((item) => item.name)).toEqual(['路程', '游玩'])
    expect(parsed.days[0].categories[0].segments[0]).toMatchObject({
      time: '06:30-14:37',
      title: '从杭州前往厦门北站',
      cost: '¥400',
      why: '尽量选省心路线。',
      attention: '预留换乘时间。',
    })
  })
})
