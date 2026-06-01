<template>
  <div class="trip-list-page">
    <header class="workbench-topbar">
      <button class="session-drawer-toggle" type="button" @click="sessionDrawerOpen = true" aria-label="会话列表">
        <el-icon><Grid /></el-icon>
        <span v-if="recentSessions.length" class="session-count-badge">{{ recentSessions.length }}</span>
      </button>
      <div class="brand-lockup">
        <div class="brand-mark">
          <el-icon><MapLocation /></el-icon>
        </div>
        <div>
          <h1>RealTrip</h1>
          <span>清新自由行规划助手</span>
        </div>
      </div>
      <div class="route-search">搜索城市、景点、酒店或餐厅</div>
      <el-tag v-if="healthStatus === 'ok'" type="success" size="small" effect="plain">在线</el-tag>
      <el-tag v-else type="danger" size="small" effect="plain">离线</el-tag>
      <div class="topbar-actions">
        <el-tag v-if="resumeNotice" size="small" effect="plain">{{ resumeNotice }}</el-tag>
        <el-button size="small" plain @click="startNewSession">新会话</el-button>
      </div>
    </header>

    <main class="workbench-shell">

      <section class="planning-control">
        <aside class="intent-panel surface-card">
          <div class="panel-kicker">旅行偏好</div>
          <h2>先确认旅行目标，再展开地图路线</h2>
          <div class="preference-grid">
            <span>交通方便</span>
            <span>预算可控</span>
            <span>轻松节奏</span>
            <span>美食路线</span>
          </div>
          <div class="draft-list">
            <button type="button" @click="setDraft('杭州4天，带老人，预算2万，慢节奏')">杭州家庭慢游</button>
            <button type="button" @click="setDraft('南京3天，第一次去，想看经典景点和本地美食')">南京经典初游</button>
            <button type="button" @click="setDraft('上海2天，预算少一点，交通方便优先')">上海省钱短途</button>
          </div>
        </aside>

        <section class="chat-panel surface-card">
          <div class="panel-head">
            <div>
              <span>AI 规划问答</span>
              <strong>把旅行想法说清楚</strong>
            </div>
          </div>
          <div ref="msgContainer" class="message-list">
            <div
              v-for="(msg, i) in messages"
              :key="i"
              class="message-row"
              :class="msg.role === 'user' ? 'is-user' : 'is-assistant'"
            >
              <div
                class="message-bubble"
                :class="{ 'is-plan-note': msg.role === 'assistant' && msg.type === 'plan_note' }"
              >
                <div class="message-text">{{ msg.content }}</div>
              </div>
            </div>

            <div v-if="loading" class="message-row is-assistant">
              <div class="message-bubble loading-bubble">
                <el-icon class="is-loading"><Loading /></el-icon>
                <span>正在规划</span>
              </div>
            </div>
          </div>

          <div class="composer">
            <el-input
              v-model="input"
              type="textarea"
              :rows="2"
              placeholder="例如：杭州4天，带老人，预算2万，慢节奏"
              @keydown.enter.exact.prevent="handleSend"
              :disabled="loading"
            />
            <el-button type="primary" @click="handleSend" :loading="loading">
              <el-icon><Promotion /></el-icon>
              发送
            </el-button>
          </div>
        </section>

        <aside class="summary-panel surface-card">
          <div class="panel-head">
            <div>
              <span>行程摘要</span>
              <strong>{{ parsedPlan.title }}</strong>
            </div>
            <el-tag v-if="hasFinalPlan" type="success" size="small" effect="plain">已生成</el-tag>
          </div>
          <div class="summary-grid">
            <div v-for="item in summaryItems" :key="item.label">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
          <el-button
            class="drawer-action"
            type="primary"
            plain
            :disabled="!hasFinalPlan || !parsedPlan.days.length"
            @click="itineraryDrawerOpen = true"
          >
            查看完整行程
          </el-button>
        </aside>
      </section>

      <section class="map-stage">
        <div class="map-toolbar">
          <span>路线概览</span>
          <button type="button" :class="{ 'is-active': !hasFinalPlan }">规划中</button>
          <button
            v-for="day in parsedPlan.days"
            :key="day.title"
            type="button"
          >
            {{ dayLabel(day.title) }}
          </button>
        </div>
        <div class="route-orbit"></div>
        <span class="route-pin route-pin-one"></span>
        <span class="route-pin route-pin-two"></span>
        <span class="route-pin route-pin-three"></span>
        <span class="route-pin route-pin-four"></span>

        <div class="map-empty" v-if="!hasFinalPlan || !parsedPlan.days.length">
          <strong>路线画布待生成</strong>
          <span>完成目的地、天数、预算和偏好确认后，这里会展示路线概览。后期可以直接替换为真实地图。</span>
        </div>

        <div v-else class="map-route-cards">
          <button
            v-for="day in parsedPlan.days"
            :key="day.title"
            type="button"
            class="route-card"
            @click="itineraryDrawerOpen = true"
          >
            <strong>{{ dayLabel(day.title) }}</strong>
            <span>{{ day.note || firstSegmentTitle(day) }}</span>
          </button>
        </div>
      </section>

      <div
        v-if="itineraryDrawerOpen"
        class="drawer-backdrop"
        @click.self="itineraryDrawerOpen = false"
      >
        <aside class="itinerary-drawer">
          <div class="drawer-head">
            <div
              class="drawer-grip"
              aria-hidden="true"
            ></div>
            <div>
              <span>完整行程</span>
              <strong>{{ parsedPlan.title }}</strong>
            </div>
            <el-button text @click="itineraryDrawerOpen = false">关闭</el-button>
          </div>

          <div class="drawer-scroll">
            <div v-if="hasFinalPlan && parsedPlan.days.length" class="plan-result-card">
              <div class="plan-summary-strip">
                <span v-for="item in parsedPlan.summary" :key="item">{{ item }}</span>
              </div>

              <section v-for="day in parsedPlan.days" :key="day.title" class="plan-day-card">
                <div class="plan-day-head">
                  <h3>{{ day.title }}</h3>
                  <p v-if="day.note">{{ day.note }}</p>
                </div>

                <div class="plan-category-list">
                  <div
                    v-for="category in day.categories"
                    :key="`${day.title}-${category.name}`"
                    class="plan-category"
                  >
                    <div class="segment-stack">
                      <article
                        v-for="segment in category.segments"
                        :key="`${segment.time}-${segment.title}`"
                        class="plan-segment"
                        :class="categoryClass(category.name)"
                      >
                        <div class="segment-main">
                          <span class="category-chip" :class="categoryClass(category.name)">
                            {{ category.name }}
                          </span>
                          <time>{{ segment.time }}</time>
                          <strong>{{ segment.title }}</strong>
                          <span v-if="segment.cost" class="segment-price">{{ segment.cost }}</span>
                        </div>
                        <details v-if="segment.attention" class="segment-details">
                          <summary>注意事项</summary>
                          <div>
                            <span>{{ segment.attention }}</span>
                          </div>
                        </details>
                      </article>
                    </div>
                  </div>
                </div>
              </section>
            </div>

            <div v-else class="empty-result">
              <strong>还没有最终行程</strong>
              <span>和我聊清楚目的地、日期、预算和偏好后，完整行程会显示在这里。</span>
            </div>
          </div>
        </aside>
      </div>
    </main>
  </div>

  <!-- 浮动会话抽屉遮罩 -->
  <div v-if="sessionDrawerOpen" class="drawer-overlay" @click="sessionDrawerOpen = false" />

  <!-- 浮动会话抽屉 -->
  <aside class="session-drawer" :class="{ 'is-open': sessionDrawerOpen }">
    <div class="drawer-inner-head">
      <div>
        <span>最近会话</span>
        <strong>{{ recentSessions.length ? `${recentSessions.length} 个行程` : '暂无记录' }}</strong>
      </div>
      <el-button text class="drawer-close-btn" @click="sessionDrawerOpen = false">
        <el-icon><Close /></el-icon>
      </el-button>
    </div>
    <button type="button" class="session-new" @click="startNewSession(); sessionDrawerOpen = false">新会话</button>
    <div class="session-list" v-if="recentSessions.length">
      <button
        v-for="item in recentSessions.slice(0, 8)"
        :key="item.session_id"
        type="button"
        class="session-item"
        :class="{ 'is-active': item.session_id === activeSessionId }"
        @click="selectSession(item.session_id); sessionDrawerOpen = false"
      >
        <strong>{{ item.title }}</strong>
        <span>{{ formatSessionMeta(item) }}</span>
        <small v-if="item.last_message_preview">{{ item.last_message_preview }}</small>
      </button>
    </div>
    <div v-else class="session-empty">
      <strong>还没有最近会话</strong>
      <span>开始规划后，历史行程会出现在这里。</span>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted, computed } from 'vue'

import {
  parsePlanMessage as parseStoredPlanMessage,
  type ParsedPlanMessage,
  type PlanCategoryView,
  type PlanDayView,
  type PlanSegmentView,
} from '@/utils/planParser'
import { planViewToParsedPlan } from '@/utils/planViewAdapter'
import type { ChatResponse, PlanView, SessionResumeResponse } from '@/types'

interface SessionSummary {
  session_id: string
  title: string
  updated_at?: string
  last_message_preview?: string
  suggested_next_action?: string
  last_trip_id?: string
}

const msgContainer = ref<HTMLElement>()
const input = ref('')
const loading = ref(false)
const healthStatus = ref('')
const resumeNotice = ref('')
const planContent = ref('')
const structuredPlan = ref<PlanView | null>(null)
const SESSION_STORAGE_KEY = 'realtrip.currentSessionId'
const SESSION_INDEX_KEY = 'realtrip.sessionIndex'
let sessionId: string | null = null
const activeSessionId = ref('')
const recentSessions = ref<SessionSummary[]>([])
const itineraryDrawerOpen = ref(false)
const sessionDrawerOpen = ref(false)

const messages = ref<{ role: string; content: string; type?: string }[]>([
  { role: 'assistant', content: '想从哪里出发，去哪里，玩几天？把预算、同行人和偏好也告诉我。' },
])

const parsedPlan = computed(() => (
  structuredPlan.value ? planViewToParsedPlan(structuredPlan.value) : parseStoredPlanMessage(planContent.value)
))
const hasFinalPlan = computed(() => Boolean(structuredPlan.value || planContent.value))
const summaryItems = computed(() => {
  if (structuredPlan.value) {
    return [
      { label: '天数', value: `${structuredPlan.value.day_count || structuredPlan.value.days.length} 天` },
      { label: '预算', value: formatMoney(structuredPlan.value.budget?.amount) },
      { label: '预计花费', value: formatMoney(structuredPlan.value.total_cost?.amount) },
      { label: '目的地', value: structuredPlan.value.destination || '待确认' },
    ]
  }

  if (parsedPlan.value.summary.length) {
    const values = parsedPlan.value.summary.slice(0, 4)
    return values.map((item, index) => ({
      label: ['概览', '预算', '节奏', '偏好'][index] || '摘要',
      value: item.replace(/^[^\u4e00-\u9fa5A-Za-z0-9]+/, ''),
    }))
  }

  return [
    { label: '天数', value: '待确认' },
    { label: '预算', value: '待确认' },
    { label: '路线', value: '待生成' },
    { label: '节奏', value: '待确认' },
  ]
})

onMounted(async () => {
  try {
    const r = await fetch('/health')
    const d = await r.json()
    healthStatus.value = d.status
  } catch { healthStatus.value = 'error' }

  await refreshSessionIndex()
  const savedSessionId = localStorage.getItem(SESSION_STORAGE_KEY)
  if (savedSessionId) {
    await restoreSession(savedSessionId)
  }
})

function setDraft(value: string) {
  input.value = value
}

function readSessionIds(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(SESSION_INDEX_KEY) || '[]')
    return Array.isArray(raw) ? raw.filter((id) => typeof id === 'string' && id) : []
  } catch {
    return []
  }
}

function writeSessionIds(ids: string[]) {
  localStorage.setItem(SESSION_INDEX_KEY, JSON.stringify(Array.from(new Set(ids)).slice(0, 20)))
}

function rememberSessionId(id: string) {
  const next = [id, ...readSessionIds().filter((item) => item !== id)]
  writeSessionIds(next)
  localStorage.setItem(SESSION_STORAGE_KEY, id)
  activeSessionId.value = id
}

function upsertSessionSummary(data: any) {
  if (!data?.session_id) return
  const summary = toSessionSummary(data)
  const rest = recentSessions.value.filter((item) => item.session_id !== summary.session_id)
  recentSessions.value = [summary, ...rest].sort(compareSessionsByTime)
}

function toSessionSummary(data: any): SessionSummary {
  return {
    session_id: data.session_id,
    title: data.title || '未命名会话',
    updated_at: data.updated_at,
    last_message_preview: data.last_message_preview || '',
    suggested_next_action: data.suggested_next_action,
    last_trip_id: data.last_trip_id,
  }
}

function compareSessionsByTime(a: SessionSummary, b: SessionSummary) {
  return new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime()
}

async function refreshSessionIndex() {
  const summaries = new Map<string, SessionSummary>()
  const validIds = new Set<string>()
  try {
    const res = await fetch('/api/sessions/recent?limit=20')
    if (res.ok) {
      const data = await res.json()
      if (Array.isArray(data)) {
        for (const item of data) {
          if (!item?.session_id) continue
          summaries.set(item.session_id, toSessionSummary(item))
          validIds.add(item.session_id)
        }
      }
    }
  } catch {
    // Local ids below still give us a recovery path when the server list is unavailable.
  }

  for (const id of readSessionIds()) {
    if (summaries.has(id)) continue
    try {
      const res = await fetch(`/api/sessions/${id}/resume`)
      if (res.status === 404) continue
      if (!res.ok) {
        validIds.add(id)
        continue
      }
      const data = await res.json()
      if (data.can_resume) {
        summaries.set(data.session_id, toSessionSummary(data))
      }
      validIds.add(id)
    } catch {
      validIds.add(id)
    }
  }

  const sorted = Array.from(summaries.values()).sort(compareSessionsByTime)
  recentSessions.value = sorted
  writeSessionIds(sorted.map((item) => item.session_id).concat(Array.from(validIds)))
}

async function restoreSession(savedSessionId: string) {
  try {
    const res = await fetch(`/api/sessions/${savedSessionId}/resume`)
    if (res.status === 404) {
      localStorage.removeItem(SESSION_STORAGE_KEY)
      return
    }
    if (!res.ok) return

    const data = await res.json() as SessionResumeResponse
    if (!data.can_resume) return

    sessionId = data.session_id
    rememberSessionId(data.session_id)
    upsertSessionSummary(data)
    structuredPlan.value = data.plan || null
    if (Array.isArray(data.messages) && data.messages.length) {
      const lastPlan = [...data.messages].reverse().find((msg) => msg.type === 'plan')
      planContent.value = lastPlan?.content || ''
      messages.value = data.messages.map((msg: any) => ({
        role: msg.role,
        content: msg.type === 'plan' ? '行程已恢复，可以打开完整行程查看最终结果。' : msg.content,
        type: msg.type === 'plan' ? 'plan_note' : undefined,
      }))
      resumeNotice.value = '已恢复上次会话'
      scrollToBottom()
    }
  } catch {
    return
  }
}

async function selectSession(id: string) {
  if (loading.value) return
  await restoreSession(id)
}

function startNewSession() {
  sessionId = null
  activeSessionId.value = ''
  planContent.value = ''
  structuredPlan.value = null
  itineraryDrawerOpen.value = false
  sessionDrawerOpen.value = false
  localStorage.removeItem(SESSION_STORAGE_KEY)
  resumeNotice.value = ''
  messages.value = [
    { role: 'assistant', content: '想从哪里出发，去哪里，玩几天？把预算、同行人和偏好也告诉我。' },
  ]
}

function formatSessionMeta(item: SessionSummary): string {
  const action = item.suggested_next_action === 'view_trip' ? '已生成方案' : '可继续'
  if (!item.updated_at) return action
  const date = new Date(item.updated_at)
  if (Number.isNaN(date.getTime())) return action
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  const time = sameDay
    ? date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
  return `${time} · ${action}`
}

async function handleSend() {
  const text = input.value.trim()
  if (!text || loading.value) return

  messages.value.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true
  scrollToBottom()

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: sessionId }),
    })
    const data = await res.json() as ChatResponse
    sessionId = data.session_id || sessionId
    if (sessionId) {
      rememberSessionId(sessionId)
    }

    if (data.type === 'question') {
      messages.value.push({ role: 'assistant', content: data.content })
    } else if (data.type === 'plan_result') {
      structuredPlan.value = data.plan || null
      planContent.value = data.content
      itineraryDrawerOpen.value = true
      messages.value.push({ role: 'assistant', type: 'plan_note', content: '行程已生成，可以打开完整行程查看结果。你也可以继续说想怎么调整。' })
    } else {
      messages.value.push({ role: 'assistant', content: '请求失败：' + data.content })
    }
    if (sessionId) {
      await refreshSessionIndex()
    }
  } catch (e: any) {
    messages.value.push({ role: 'assistant', content: '请求失败：' + e.message })
  }

  loading.value = false
  scrollToBottom()
}

function scrollToBottom() {
  nextTick(() => {
    if (msgContainer.value) {
      msgContainer.value.scrollTop = msgContainer.value.scrollHeight
    }
  })
}

function formatMoney(amount?: number): string {
  if (!amount) return '待确认'
  return `¥${amount.toLocaleString('zh-CN')}`
}

function dayLabel(title: string): string {
  const match = title.match(/(?:第|Day\s*)(\d+)/i)
  if (match) return `Day ${match[1]}`
  return title.split(/[｜|—-]/)[0]?.trim() || title
}

function firstSegmentTitle(day: PlanDayView): string {
  for (const category of day.categories) {
    const segment = category.segments[0]
    if (segment?.title) return segment.title
  }
  return '点击查看当天路线详情'
}

function parsePlanMessage(content: string): ParsedPlanMessage {
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

    if (line.startsWith('✅')) {
      result.title = line.replace(/^✅\s*/, '').replace(/！$/, '')
      continue
    }

    if (line.startsWith('📍') || line.startsWith('💰') || line.startsWith('节奏：')) {
      result.summary.push(line)
      continue
    }

    if (line.startsWith('📅')) {
      currentDay = { title: line, note: '', categories: [] }
      result.days.push(currentDay)
      currentCategory = null
      currentSegment = null
      continue
    }

    if (!currentDay) continue

    if (line.startsWith('——') && line.endsWith('——')) {
      currentCategory = {
        name: line.replace(/——/g, '').trim(),
        segments: [],
      }
      currentDay.categories.push(currentCategory)
      currentSegment = null
      continue
    }

    if (line.startsWith('为什么推荐：')) {
      if (currentSegment) currentSegment.why = line.replace('为什么推荐：', '').trim()
      continue
    }

    if (line.startsWith('注意事项：')) {
      if (currentSegment) currentSegment.attention = line.replace('注意事项：', '').trim()
      continue
    }

    const segmentMatch = line.match(/^([\d:]{4,5}-[\d:]{4,5})\s+(.+)$/)
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
  const match = value.match(/\s([¥￥]\s?[\d,]+(?:\.\d+)?)$/)
  if (!match) return { title: value, cost: '' }
  return {
    title: value.slice(0, match.index).trim(),
    cost: match[1].replace(/\s+/g, ''),
  }
}

function categoryClass(name: string): string {
  if (name.includes('用餐')) return 'is-meal'
  if (name.includes('游玩')) return 'is-activity'
  if (name.includes('路程')) return 'is-transport'
  if (name.includes('住宿')) return 'is-hotel'
  return ''
}

</script>

<style scoped>
.trip-list-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  background:
    linear-gradient(90deg, rgba(17, 24, 20, 0.88) 0, rgba(17, 24, 20, 0.88) 1px, transparent 1px) 0 0 / 84px 84px,
    linear-gradient(180deg, rgba(17, 24, 20, 0.7), transparent 28%),
    radial-gradient(circle at 9% 15%, rgba(183, 121, 65, 0.2), transparent 26%),
    var(--rt-bg);
}

.trip-list-page::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(115deg, rgba(255, 253, 247, 0.08), transparent 28%),
    radial-gradient(circle at 86% 86%, rgba(217, 231, 237, 0.38), transparent 24%);
  mix-blend-mode: multiply;
}

.app-topbar {
  position: relative;
  z-index: 1;
  height: 72px;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 32px;
  background: rgba(255, 253, 247, 0.78);
  border-bottom: 1px solid rgba(73, 65, 48, 0.18);
  backdrop-filter: blur(22px);
  box-shadow: 0 12px 42px rgba(38, 32, 20, 0.08);
}

.brand-lockup {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.brand-mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: #fffdf7;
  background:
    linear-gradient(135deg, rgba(183, 121, 65, 0.94), rgba(36, 71, 63, 0.98));
  box-shadow: 0 16px 30px rgba(36, 71, 63, 0.28);
}

.brand-lockup h1 {
  margin: 0;
  font-family: 'Palatino Linotype', 'Noto Serif SC', serif;
  font-size: 20px;
  line-height: 1.2;
  letter-spacing: 0;
  white-space: nowrap;
}

.brand-lockup span {
  color: var(--rt-muted);
  font-size: 12.5px;
}

.chat-shell {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: 0;
  width: min(1480px, 100%);
  display: grid;
  grid-template-columns: 286px minmax(0, 1.08fr) 444px;
  gap: 14px;
  margin: 0 auto;
  padding: 18px;
  overflow: hidden;
}

.context-panel,
.chat-panel,
.result-panel {
  border: 1px solid var(--rt-border);
  border-radius: 8px;
  background: rgba(255, 253, 247, 0.82);
  box-shadow: var(--rt-shadow);
  backdrop-filter: blur(20px);
}

.context-panel {
  min-height: 0;
  padding: 24px;
  overflow-y: auto;
  background:
    linear-gradient(180deg, rgba(255, 253, 247, 0.9), rgba(241, 234, 223, 0.72)),
    radial-gradient(circle at 88% 8%, rgba(183, 121, 65, 0.2), transparent 34%);
}

.panel-kicker {
  width: fit-content;
  padding: 5px 9px;
  border: 1px solid rgba(183, 121, 65, 0.24);
  border-radius: 999px;
  background: rgba(183, 121, 65, 0.1);
  color: var(--rt-accent);
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 14px;
}

.context-panel h2 {
  margin: 0 0 22px;
  font-family: 'Palatino Linotype', 'Noto Serif SC', serif;
  font-size: 29px;
  line-height: 1.18;
  letter-spacing: 0;
}

.metric-grid {
  display: grid;
  gap: 12px;
  margin-bottom: 22px;
}

.metric-grid div {
  padding: 14px;
  border: 1px solid rgba(73, 65, 48, 0.14);
  border-radius: 8px;
  background: rgba(255, 253, 247, 0.68);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.76);
}

.metric-grid span {
  display: block;
  margin-bottom: 4px;
  color: var(--rt-muted);
  font-size: 12px;
}

.metric-grid strong {
  font-size: 14.5px;
  line-height: 1.45;
}

.draft-list {
  display: grid;
  gap: 10px;
}

.draft-list button {
  width: 100%;
  padding: 12px 13px;
  border: 1px solid var(--rt-border);
  border-radius: 8px;
  background: rgba(255, 253, 247, 0.76);
  color: var(--rt-text);
  text-align: left;
  cursor: pointer;
  box-shadow: 0 9px 24px rgba(38, 32, 20, 0.05);
  transition: border-color 160ms ease, transform 160ms ease, box-shadow 160ms ease;
}

.draft-list button:hover {
  border-color: rgba(183, 121, 65, 0.38);
  background: var(--rt-accent-soft);
  box-shadow: 0 14px 30px rgba(38, 32, 20, 0.1);
  transform: translateY(-1px);
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}


.chat-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background:
    linear-gradient(180deg, rgba(255, 253, 247, 0.94), rgba(255, 253, 247, 0.76)),
    radial-gradient(circle at 50% 0%, rgba(217, 231, 237, 0.64), transparent 34%);
}

.result-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background:
    linear-gradient(180deg, rgba(18, 27, 23, 0.94), rgba(30, 44, 38, 0.92)),
    radial-gradient(circle at 88% 8%, rgba(183, 121, 65, 0.22), transparent 32%);
  color: #fff9ed;
}

.result-panel-head {
  min-height: 74px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid rgba(255, 253, 247, 0.12);
  background: rgba(255, 253, 247, 0.05);
}

.result-panel-head span {
  display: block;
  margin-bottom: 3px;
  color: rgba(255, 249, 237, 0.58);
  font-size: 12px;
  font-weight: 700;
}

.result-panel-head strong {
  display: block;
  color: #fff9ed;
  font-family: 'Palatino Linotype', 'Noto Serif SC', serif;
  font-size: 19px;
  line-height: 1.3;
}

.result-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.empty-result {
  min-height: 100%;
  display: grid;
  place-content: center;
  gap: 8px;
  padding: 28px;
  color: rgba(255, 249, 237, 0.62);
  text-align: center;
}

.empty-result strong {
  color: #fff9ed;
  font-size: 16px;
}

.empty-result span {
  max-width: 300px;
  font-size: 13px;
  line-height: 1.7;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 28px;
}

.message-row {
  display: flex;
  margin-bottom: 16px;
}

.message-row.is-user {
  justify-content: flex-end;
}

.message-row.is-assistant {
  justify-content: flex-start;
}

.message-bubble {
  max-width: min(680px, 86%);
  padding: 13px 16px;
  border: 1px solid var(--rt-border);
  border-radius: 8px;
  background: rgba(255, 253, 247, 0.9);
  color: var(--rt-text);
  box-shadow: 0 12px 34px rgba(38, 32, 20, 0.08);
}

.message-bubble.is-plan-bubble {
  width: min(880px, 96%);
  max-width: min(880px, 96%);
  padding: 0;
  overflow: hidden;
  background: #f8fafc;
}

.message-bubble.is-plan-note {
  border-color: rgba(39, 116, 91, 0.22);
  background: rgba(226, 238, 231, 0.76);
  color: var(--rt-success);
}

.is-user .message-bubble {
  border-color: transparent;
  background: linear-gradient(135deg, var(--rt-primary) 0%, #356557 100%);
  color: #fffdf7;
  box-shadow: 0 18px 38px rgba(36, 71, 63, 0.24);
}

.message-text {
  white-space: pre-wrap;
  line-height: 1.65;
  font-size: 14px;
}

.plan-alert {
  margin: 0;
  border-width: 0 0 1px;
  border-radius: 0;
}

.plan-result-card {
  padding: 16px;
}

.plan-result-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.plan-result-head strong {
  font-size: 18px;
  line-height: 1.3;
}

.status-pill {
  display: inline-grid;
  place-items: center;
  min-width: 58px;
  height: 26px;
  padding: 0 10px;
  border: 1px solid #bbf7d0;
  border-radius: 999px;
  background: #f0fdf4;
  color: #15803d;
  font-size: 12px;
  font-weight: 700;
}

.plan-summary-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 9px;
  margin-bottom: 16px;
}

.plan-summary-strip span {
  min-height: 48px;
  display: flex;
  align-items: center;
  padding: 10px 11px;
  border: 1px solid rgba(255, 253, 247, 0.12);
  border-radius: 8px;
  background: rgba(255, 253, 247, 0.08);
  color: rgba(255, 249, 237, 0.86);
  font-size: 13px;
  line-height: 1.35;
}

.plan-day-card {
  border: 1px solid rgba(255, 253, 247, 0.13);
  border-radius: 8px;
  background: rgba(255, 253, 247, 0.08);
  overflow: hidden;
  box-shadow: 0 18px 42px rgba(0, 0, 0, 0.14);
}

.plan-day-card + .plan-day-card {
  margin-top: 14px;
}

.plan-day-head {
  padding: 15px 16px;
  border-bottom: 1px solid rgba(255, 253, 247, 0.1);
  background: rgba(255, 253, 247, 0.07);
}

.plan-day-head h3 {
  margin: 0;
  color: #f6cf9f;
  font-family: 'Palatino Linotype', 'Noto Serif SC', serif;
  font-size: 18px;
  line-height: 1.35;
  letter-spacing: 0;
}

.plan-day-head p {
  margin: 7px 0 0;
  color: rgba(255, 249, 237, 0.6);
  font-size: 13px;
  line-height: 1.55;
}

.plan-category-list {
  display: grid;
  gap: 8px;
  padding: 14px;
}

.plan-category {
  min-width: 0;
}

.category-chip {
  min-height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 5px 9px;
  border: 1px solid rgba(217, 231, 237, 0.28);
  border-radius: 8px;
  background: rgba(217, 231, 237, 0.12);
  color: #d9e7ed;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.category-chip.is-meal {
  border-color: rgba(176, 216, 181, 0.28);
  background: rgba(176, 216, 181, 0.1);
  color: #b7d9bc;
}

.category-chip.is-activity {
  border-color: rgba(246, 207, 159, 0.34);
  background: rgba(246, 207, 159, 0.12);
  color: #f6cf9f;
}

.category-chip.is-transport {
  border-color: rgba(217, 231, 237, 0.24);
  background: rgba(217, 231, 237, 0.08);
  color: #c6d8de;
}

.category-chip.is-hotel {
  border-color: rgba(204, 176, 150, 0.32);
  background: rgba(204, 176, 150, 0.1);
  color: #dcc1a7;
}

.segment-stack {
  display: grid;
  gap: 8px;
}

.plan-segment {
  padding: 13px;
  border: 1px solid rgba(255, 253, 247, 0.12);
  border-radius: 8px;
  background: rgba(255, 253, 247, 0.075);
}

.plan-segment.is-transport {
  padding: 8px 10px;
  border-style: dashed;
  background: rgba(217, 231, 237, 0.055);
  border-color: rgba(217, 231, 237, 0.14);
  box-shadow: none;
  opacity: 0.9;
}

.plan-segment.is-meal {
  padding: 10px 11px;
  background: rgba(176, 216, 181, 0.055);
  border-color: rgba(176, 216, 181, 0.14);
  box-shadow: none;
}

.plan-segment.is-activity {
  padding: 15px 15px 14px;
  border-color: rgba(246, 207, 159, 0.2);
  background: linear-gradient(180deg, rgba(255, 253, 247, 0.14) 0%, rgba(246, 207, 159, 0.06) 100%);
  box-shadow: 0 16px 32px rgba(0, 0, 0, 0.14);
}

.plan-segment.is-hotel {
  margin-top: 4px;
  border-color: rgba(204, 176, 150, 0.18);
  background: rgba(204, 176, 150, 0.055);
}

.plan-segment.is-meal .segment-main strong,
.plan-segment.is-transport .segment-main strong {
  color: rgba(255, 249, 237, 0.76);
  font-weight: 580;
}

.plan-segment.is-transport .category-chip,
.plan-segment.is-meal .category-chip {
  transform: scale(0.9);
  transform-origin: left center;
}

.plan-segment.is-transport .segment-main {
  grid-template-columns: auto 78px minmax(0, 1fr) auto;
}

.plan-segment.is-hotel .segment-main strong {
  color: #ead2bb;
}

.segment-main {
  display: grid;
  grid-template-columns: auto 90px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
}

.segment-main time {
  color: rgba(255, 249, 237, 0.52);
  font-size: 12px;
  line-height: 1.5;
  white-space: nowrap;
}

.segment-main strong {
  color: #fff9ed;
  font-size: 14px;
  line-height: 1.55;
  font-weight: 650;
}

.plan-segment.is-activity .segment-main strong {
  color: #fff9ed;
  font-size: 17px;
  line-height: 1.5;
  font-weight: 760;
}

.plan-segment.is-activity .segment-main time,
.plan-segment.is-activity .segment-price {
  color: #f6cf9f;
}

.plan-segment.is-transport .segment-main time,
.plan-segment.is-meal .segment-main time {
  font-size: 11px;
  color: rgba(255, 249, 237, 0.45);
}

.plan-segment.is-transport .segment-main strong {
  font-size: 13px;
  line-height: 1.45;
}

.plan-segment.is-meal .segment-main strong {
  font-size: 13px;
  line-height: 1.5;
}

.segment-price {
  color: #f2c77e;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
}

.plan-segment.is-transport .segment-price,
.plan-segment.is-meal .segment-price {
  color: #d6ae70;
  font-size: 12px;
  font-weight: 600;
}

.segment-details {
  margin-top: 10px;
  border-top: 1px solid rgba(255, 253, 247, 0.12);
  padding-top: 8px;
}

.segment-details summary {
  width: fit-content;
  cursor: pointer;
  color: #d9e7ed;
  font-size: 12px;
  font-weight: 650;
  list-style: none;
}

.segment-details summary::-webkit-details-marker {
  display: none;
}

.segment-details summary::before {
  content: '＋';
  margin-right: 5px;
}

.segment-details[open] summary::before {
  content: '－';
}

.segment-details div {
  margin-top: 8px;
  color: rgba(255, 249, 237, 0.64);
  font-size: 13px;
  line-height: 1.7;
}

.loading-bubble {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--rt-muted);
}

.composer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  padding: 18px;
  border-top: 1px solid var(--rt-border);
  background: rgba(255, 253, 247, 0.76);
}

.composer .el-button {
  height: 62px;
  min-width: 92px;
}

.trip-list-page {
  min-height: 100vh;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background:
    radial-gradient(circle at 12% 10%, rgba(42, 157, 143, 0.16), transparent 26%),
    radial-gradient(circle at 82% 8%, rgba(255, 190, 92, 0.2), transparent 24%),
    linear-gradient(145deg, #fbfffd 0%, #e9f8f5 52%, #fff8e8 100%);
}

.trip-list-page::before {
  background:
    linear-gradient(90deg, rgba(47, 118, 130, 0.07) 0, rgba(47, 118, 130, 0.07) 1px, transparent 1px) 0 0 / 88px 88px,
    linear-gradient(180deg, rgba(255, 255, 255, 0.32), transparent 30%);
  mix-blend-mode: normal;
}

.workbench-topbar {
  position: relative;
  z-index: 5;
  height: 68px;
  display: grid;
  grid-template-columns: auto minmax(190px, auto) minmax(260px, 560px) auto auto;
  align-items: center;
  gap: 14px;
  padding: 0 22px;
  border-bottom: 1px solid rgba(47, 118, 130, 0.14);
  background: rgba(255, 255, 255, 0.72);
  box-shadow: 0 12px 38px rgba(56, 120, 137, 0.08);
  backdrop-filter: blur(18px);
}

.workbench-topbar .brand-lockup {
  flex: initial;
}

.brand-mark {
  border-radius: 13px;
  background: linear-gradient(135deg, #2a9d8f 0%, #7bdff2 100%);
  box-shadow: 0 14px 30px rgba(42, 157, 143, 0.28);
}

.brand-lockup h1 {
  font-family: Aptos, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: 19px;
  font-weight: 850;
}

.brand-lockup span {
  color: #345963;
  font-weight: 650;
}

.route-search {
  height: 42px;
  display: flex;
  align-items: center;
  min-width: 0;
  padding: 0 16px;
  border: 1px solid rgba(31, 90, 101, 0.22);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.94);
  color: #2f5862;
  font-size: 13px;
  font-weight: 650;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
}

.workbench-shell {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: 0;
  width: min(1480px, 100%);
  display: grid;
  grid-template-columns: 1fr;
  grid-template-rows: minmax(230px, 0.42fr) minmax(0, 0.58fr);
  gap: 14px;
  margin: 0 auto;
  padding: 14px;
  overflow: hidden;
}

.planning-control {
  grid-column: 2;
  grid-row: 1;
}

.map-stage {
  grid-column: 2;
  grid-row: 2;
}

.planning-control {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(270px, 0.84fr) minmax(380px, 1.18fr) minmax(280px, 0.9fr);
  gap: 14px;
}

.surface-card {
  min-height: 0;
  border: 1px solid rgba(31, 90, 101, 0.2);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 18px 50px rgba(56, 120, 137, 0.1);
  overflow: hidden;
  backdrop-filter: blur(16px);
}

.intent-panel {
  display: flex;
  flex-direction: column;
  padding: 18px;
}

.intent-panel .panel-kicker {
  margin-bottom: 12px;
  border-color: rgba(42, 157, 143, 0.18);
  background: #e6f8f5;
  color: #248277;
}

.intent-panel h2 {
  margin: 0 0 14px;
  color: var(--rt-primary-ink);
  font-size: 25px;
  line-height: 1.18;
  font-weight: 850;
}

.preference-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.preference-grid span,
.map-toolbar button,
.map-toolbar span {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  padding: 0 10px;
  border-radius: 999px;
  background: var(--rt-accent-soft);
  color: #9b6a24;
  font-size: 12px;
  font-weight: 760;
}

.draft-list {
  grid-template-columns: 1fr;
  gap: 8px;
}

.draft-list button {
  min-height: 38px;
  padding: 9px 11px;
  border-color: rgba(47, 118, 130, 0.12);
  background: rgba(255, 255, 255, 0.74);
  box-shadow: none;
}

.draft-list button:hover {
  border-color: rgba(42, 157, 143, 0.35);
  background: #eef9f7;
  transform: none;
}

.chat-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  background: rgba(255, 255, 255, 0.78);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px 10px;
}

.panel-head span {
  display: block;
  margin-bottom: 3px;
  color: #345963;
  font-size: 12px;
  font-weight: 820;
}

.panel-head strong {
  display: block;
  color: var(--rt-primary-ink);
  font-size: 18px;
  line-height: 1.3;
}

.message-list {
  padding: 8px 18px 12px;
}

.message-bubble {
  border-color: rgba(31, 90, 101, 0.16);
  border-radius: 16px;
  background: #f7fdfb;
  color: #123e45;
  box-shadow: none;
}

.is-user .message-bubble {
  background: linear-gradient(135deg, #2a9d8f, #52b6aa);
  box-shadow: 0 14px 28px rgba(42, 157, 143, 0.2);
}

.message-bubble.is-plan-note {
  background: #e6f8f5;
  color: #168773;
}

.composer {
  padding: 12px 16px 16px;
  border-top: 0;
  background: transparent;
}

.composer .el-button {
  height: 58px;
}

.summary-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  padding-bottom: 16px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 0 16px;
}

.summary-grid div {
  min-height: 58px;
  padding: 10px 11px;
  border-radius: 14px;
  background: #f7fdfb;
  border: 1px solid rgba(31, 90, 101, 0.12);
}

.summary-grid span {
  display: block;
  margin-bottom: 7px;
  color: #345963;
  font-size: 12px;
  font-weight: 820;
}

.summary-grid strong {
  display: block;
  overflow: hidden;
  color: var(--rt-primary-ink);
  font-size: 15px;
  font-weight: 850;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drawer-action {
  justify-self: stretch;
  margin: 14px 16px 0;
}

.map-stage {
  position: relative;
  min-height: 0;
  border: 1px solid rgba(47, 118, 130, 0.18);
  border-radius: 26px;
  background:
    linear-gradient(35deg, transparent 42%, rgba(88, 165, 160, 0.24) 43%, transparent 45%),
    linear-gradient(115deg, transparent 50%, rgba(124, 189, 199, 0.28) 51%, transparent 53%),
    radial-gradient(circle at 72% 26%, rgba(255, 198, 92, 0.52), transparent 12%),
    radial-gradient(circle at 28% 70%, rgba(42, 157, 143, 0.34), transparent 18%),
    #e9f8f5;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7), 0 22px 56px rgba(56, 120, 137, 0.14);
  overflow: hidden;
}

.map-stage::before {
  content: '';
  position: absolute;
  inset: 42px 86px 38px 70px;
  border: 3px dashed rgba(42, 157, 143, 0.32);
  border-radius: 50%;
  transform: rotate(-10deg);
}

.map-toolbar {
  position: absolute;
  z-index: 2;
  top: 18px;
  left: 18px;
  right: 18px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.map-toolbar span,
.map-toolbar button {
  border: 0;
  background: rgba(255, 255, 255, 0.84);
  color: #31525a;
  box-shadow: 0 10px 26px rgba(56, 120, 137, 0.14);
  cursor: pointer;
}

.map-toolbar span {
  background: #e6f8f5;
  color: #248277;
}

.map-toolbar button.is-active {
  background: var(--rt-accent-soft);
  color: #9b6a24;
}

.route-orbit {
  position: absolute;
  left: 19%;
  top: 16%;
  width: 62%;
  height: 58%;
  border: 8px solid rgba(42, 157, 143, 0.58);
  border-left-color: transparent;
  border-bottom-color: transparent;
  border-radius: 50%;
  transform: rotate(11deg);
}

.route-pin {
  position: absolute;
  width: 24px;
  height: 24px;
  border: 5px solid white;
  border-radius: 50%;
  background: var(--rt-accent);
  box-shadow: 0 14px 28px rgba(113, 85, 31, 0.24);
}

.route-pin-one {
  left: 22%;
  top: 25%;
}

.route-pin-two {
  right: 24%;
  top: 34%;
  background: var(--rt-primary);
}

.route-pin-three {
  left: 44%;
  bottom: 18%;
  background: var(--rt-coral);
}

.route-pin-four {
  right: 16%;
  bottom: 23%;
  background: #7bdff2;
}

.map-empty {
  position: absolute;
  left: 50%;
  top: 50%;
  z-index: 2;
  display: grid;
  gap: 8px;
  width: min(360px, calc(100% - 40px));
  padding: 18px;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.94);
  color: #2f5862;
  text-align: center;
  transform: translate(-50%, -50%);
  box-shadow: 0 22px 52px rgba(56, 120, 137, 0.18);
}

.map-empty strong {
  color: var(--rt-primary-ink);
  font-size: 18px;
  font-weight: 850;
}

.map-empty span {
  color: #2f5862;
  font-weight: 620;
}

.map-route-cards {
  position: absolute;
  z-index: 2;
  left: 20px;
  right: 20px;
  bottom: 20px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px;
}

.route-card {
  min-height: 82px;
  padding: 12px;
  border: 1px solid rgba(47, 118, 130, 0.12);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.94);
  color: #345963;
  text-align: left;
  box-shadow: 0 16px 38px rgba(56, 120, 137, 0.13);
  cursor: pointer;
}

.route-card strong {
  display: block;
  margin-bottom: 8px;
  color: var(--rt-primary-ink);
  font-size: 14px;
}

.route-card span {
  display: -webkit-box;
  overflow: hidden;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.drawer-backdrop {
  position: fixed;
  z-index: 20;
  inset: 0;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding: 20px;
  background: rgba(18, 62, 69, 0.22);
  backdrop-filter: blur(8px);
}

.itinerary-drawer {
  width: min(1120px, 100%);
  max-height: min(82vh, 760px);
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  border: 1px solid rgba(47, 118, 130, 0.18);
  border-radius: 24px 24px 18px 18px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 28px 90px rgba(18, 62, 69, 0.22);
  overflow: hidden;
}

.drawer-head {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 22px 24px 16px;
  border-bottom: 1px solid rgba(47, 118, 130, 0.12);
}

.drawer-grip {
  position: absolute;
  top: 9px;
  left: 50%;
  width: 54px;
  height: 5px;
  border-radius: 999px;
  background: #c4e3e5;
  transform: translateX(-50%);
}

.drawer-head span {
  display: block;
  color: #345963;
  font-size: 12px;
  font-weight: 820;
}

.drawer-head strong {
  display: block;
  color: var(--rt-primary-ink);
  font-size: 20px;
}

.drawer-scroll {
  min-height: 0;
  overflow-y: auto;
}

.drawer-scroll .empty-result {
  min-height: 360px;
  color: #719096;
}

.drawer-scroll .empty-result strong {
  color: var(--rt-primary-ink);
}

.drawer-scroll .plan-summary-strip span,
.drawer-scroll .plan-day-card,
.drawer-scroll .plan-segment {
  border-color: rgba(47, 118, 130, 0.12);
  background: rgba(244, 251, 250, 0.82);
  color: var(--rt-primary-ink);
  box-shadow: none;
}

.drawer-scroll .plan-day-head {
  border-bottom-color: rgba(47, 118, 130, 0.12);
  background: rgba(255, 255, 255, 0.72);
}

.drawer-scroll .plan-day-head h3,
.drawer-scroll .segment-main strong {
  color: var(--rt-primary-ink);
}

.drawer-scroll .plan-day-head p,
.drawer-scroll .segment-main time,
.drawer-scroll .segment-details div {
  color: #345963;
}

.drawer-scroll .category-chip {
  border-color: rgba(42, 157, 143, 0.18);
  background: #e6f8f5;
  color: #248277;
}

.drawer-scroll .segment-price,
.drawer-scroll .segment-details summary {
  color: #9b6a24;
}

.summary-panel .panel-head strong {
  font-size: 20px;
}

.summary-grid div {
  min-height: 68px;
  padding: 12px 13px;
}

.summary-grid span {
  font-size: 13px;
  line-height: 1.35;
}

.summary-grid strong {
  font-size: 17px;
  line-height: 1.35;
}

.drawer-action {
  min-height: 42px;
  font-size: 15px;
  font-weight: 700;
}

.route-card {
  min-height: 96px;
  padding: 14px;
}

.route-card strong {
  font-size: 16px;
  line-height: 1.35;
}

.route-card span {
  font-size: 14px;
  line-height: 1.55;
  -webkit-line-clamp: 3;
}

.drawer-scroll .plan-summary-strip span {
  min-height: 54px;
  font-size: 14px;
  font-weight: 760;
  line-height: 1.45;
}

.drawer-scroll .plan-day-head {
  padding: 17px 18px;
}

.drawer-scroll .plan-day-head h3 {
  font-size: 21px;
  line-height: 1.35;
}

.drawer-scroll .plan-day-head p {
  font-size: 14.5px;
  line-height: 1.65;
}

.drawer-scroll .category-chip {
  min-height: 30px;
  padding: 6px 10px;
  font-size: 13px;
  font-weight: 800;
}

.drawer-scroll .segment-main {
  grid-template-columns: auto 104px minmax(0, 1fr) auto;
  gap: 12px;
}

.drawer-scroll .segment-main time,
.drawer-scroll .plan-segment.is-transport .segment-main time,
.drawer-scroll .plan-segment.is-meal .segment-main time {
  font-size: 13.5px;
  line-height: 1.6;
}

.drawer-scroll .segment-main strong,
.drawer-scroll .plan-segment.is-transport .segment-main strong,
.drawer-scroll .plan-segment.is-meal .segment-main strong {
  font-size: 16px;
  font-weight: 760;
  line-height: 1.6;
}

.drawer-scroll .plan-segment.is-activity .segment-main strong {
  font-size: 18px;
  line-height: 1.55;
}

.drawer-scroll .segment-price {
  font-size: 14px;
  font-weight: 800;
}

.drawer-scroll .segment-details summary {
  font-size: 13.5px;
  font-weight: 760;
}

.drawer-scroll .segment-details div {
  font-size: 14px;
  line-height: 1.7;
}

.drawer-scroll .plan-segment .segment-main strong,
.drawer-scroll .plan-segment.is-route .segment-main strong,
.drawer-scroll .plan-segment.is-activity .segment-main strong,
.drawer-scroll .plan-segment.is-meal .segment-main strong,
.drawer-scroll .plan-segment.is-transport .segment-main strong,
.drawer-scroll .plan-segment.is-hotel .segment-main strong {
  color: #123e45;
}

.drawer-scroll .plan-segment .segment-main time,
.drawer-scroll .plan-segment.is-route .segment-main time,
.drawer-scroll .plan-segment.is-activity .segment-main time,
.drawer-scroll .plan-segment.is-meal .segment-main time,
.drawer-scroll .plan-segment.is-transport .segment-main time,
.drawer-scroll .plan-segment.is-hotel .segment-main time {
  color: #2f5862;
  font-weight: 650;
}

.drawer-scroll .plan-segment .segment-price,
.drawer-scroll .plan-segment.is-activity .segment-price,
.drawer-scroll .plan-segment.is-meal .segment-price,
.drawer-scroll .plan-segment.is-transport .segment-price,
.drawer-scroll .plan-segment.is-hotel .segment-price {
  color: #8a5a12;
  font-size: 14px;
  font-weight: 800;
}

.drawer-scroll .plan-segment .segment-details div,
.drawer-scroll .plan-segment .segment-details span {
  color: #345963;
}

/* ── 浮动会话抽屉 ── */

.session-drawer-toggle {
  position: relative;
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(31, 90, 101, 0.16);
  border-radius: 13px;
  background: #f7fdfb;
  color: #2f5862;
  cursor: pointer;
  flex-shrink: 0;
  transition: border-color 160ms ease, background 160ms ease, transform 160ms ease;
}

.session-drawer-toggle:hover {
  border-color: rgba(42, 157, 143, 0.36);
  background: #e6f8f5;
  transform: translateY(-1px);
}

.session-count-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--rt-coral);
  color: #fff;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
}

.drawer-overlay {
  position: fixed;
  z-index: 29;
  inset: 0;
  background: rgba(18, 62, 69, 0.18);
  backdrop-filter: blur(4px);
  transition: opacity 240ms ease;
}

.session-drawer {
  position: fixed;
  z-index: 30;
  left: 0;
  top: 0;
  bottom: 0;
  width: 340px;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  padding: 20px;
  border-right: 1px solid rgba(31, 90, 101, 0.12);
  border-radius: 0 22px 22px 0;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 8px 0 60px rgba(18, 62, 69, 0.16);
  transform: translateX(-100%);
  transition: transform 280ms cubic-bezier(0.4, 0, 0.2, 1);
  backdrop-filter: blur(20px);
}

.session-drawer.is-open {
  transform: translateX(0);
}

.drawer-inner-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.drawer-inner-head span {
  display: block;
  margin-bottom: 4px;
  color: #345963;
  font-size: 13px;
  font-weight: 820;
}

.drawer-inner-head strong {
  display: block;
  color: var(--rt-primary-ink);
  font-size: 21px;
  line-height: 1.25;
}

.drawer-close-btn {
  flex-shrink: 0;
  color: #345963;
}

.session-drawer .session-new {
  min-height: 44px;
  padding: 0 14px;
  border: 1px solid rgba(31, 90, 101, 0.16);
  border-radius: 14px;
  background: linear-gradient(135deg, #2a9d8f, #52b6aa);
  color: #ffffff;
  font-size: 14px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 14px 30px rgba(42, 157, 143, 0.2);
  transition: border-color 160ms ease, background 160ms ease, transform 160ms ease;
}

.session-drawer .session-new:hover {
  border-color: rgba(42, 157, 143, 0.36);
  background: linear-gradient(135deg, #248277, #45a89e);
  transform: translateY(-1px);
}

.session-drawer .session-list {
  min-height: 0;
  padding-right: 4px;
  overflow-y: auto;
}

.session-drawer .session-item {
  width: 100%;
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid rgba(31, 90, 101, 0.1);
  border-radius: 14px;
  background: rgba(244, 251, 250, 0.72);
  color: var(--rt-text);
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease;
}

.session-drawer .session-item + .session-item {
  margin-top: 8px;
}

.session-drawer .session-item:hover,
.session-drawer .session-item.is-active {
  border-color: rgba(42, 157, 143, 0.34);
  background: #e6f8f5;
}

.session-drawer .session-item strong {
  overflow: hidden;
  color: #123e45;
  font-size: 14px;
  font-weight: 850;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-drawer .session-item span,
.session-drawer .session-item small {
  overflow: hidden;
  color: #345963;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-drawer .session-empty {
  display: grid;
  align-content: center;
  gap: 8px;
  min-height: 180px;
  padding: 18px;
  border: 1px dashed rgba(47, 118, 130, 0.2);
  border-radius: 16px;
  background: rgba(244, 251, 250, 0.64);
  color: #345963;
}

.session-drawer .session-empty strong {
  color: #123e45;
  font-size: 15px;
}

.session-drawer .session-empty span {
  font-size: 13px;
  line-height: 1.55;
}

@media (max-width: 960px) {
  .workbench-topbar {
    grid-template-columns: auto minmax(170px, auto) minmax(180px, 1fr) auto;
  }

  .topbar-actions .el-tag {
    display: none;
  }

  .planning-control {
    grid-template-columns: 1fr 1.4fr;
  }

  .summary-panel {
    grid-column: 1 / -1;
  }
}

@media (max-width: 820px) {
  .trip-list-page {
    height: auto;
    min-height: 100vh;
    overflow: visible;
  }

  .workbench-topbar {
    position: sticky;
    top: 0;
    grid-template-columns: auto minmax(0, 1fr) auto auto;
    gap: 8px;
    padding: 0 12px;
  }

  .route-search,
  .brand-lockup span {
    display: none;
  }

  .brand-mark {
    width: 36px;
    height: 36px;
  }

  .brand-lockup h1 {
    max-width: 120px;
    overflow: hidden;
    font-size: 18px;
    text-overflow: ellipsis;
  }

  .workbench-shell {
    height: auto;
    min-height: calc(100vh - 68px);
    grid-template-rows: auto minmax(440px, 58vh);
    overflow: visible;
  }

  .planning-control {
    grid-template-columns: 1fr;
  }

  .intent-panel {
    order: 2;
  }

  .chat-panel {
    min-height: 420px;
    order: 1;
  }

  .summary-panel {
    order: 3;
  }

  .map-stage {
    min-height: 500px;
  }

  .map-stage::before {
    inset: 70px 24px 86px;
  }

  .map-route-cards {
    grid-template-columns: 1fr;
  }

  .drawer-backdrop {
    padding: 10px;
  }

  .itinerary-drawer {
    max-height: 88vh;
    border-radius: 22px;
  }

  .segment-main {
    grid-template-columns: 1fr;
  }

  .drawer-scroll .segment-main {
    grid-template-columns: 1fr;
  }

  .session-drawer {
    width: min(320px, 88vw);
  }
}
</style>
