<template>
  <el-container class="detail-page">
    <el-header class="detail-topbar">
      <el-button text class="back-button" @click="$router.push('/')">
        <el-icon><ArrowLeft /></el-icon> 返回
      </el-button>
      <div class="detail-title">
        <div class="detail-title-icon"><el-icon><MapLocation /></el-icon></div>
        <div>
          <h1>{{ trip?.destination || '行程详情' }}</h1>
          <span v-if="trip">{{ trip.start_date }} · {{ trip.days }} 天</span>
        </div>
      </div>
      <div style="flex: 1" />
      <el-tag v-if="trip?.status === 'completed'" type="success" size="small">已完成</el-tag>
      <el-tag v-else type="warning" size="small">{{ trip?.status }}</el-tag>
    </el-header>

    <el-main class="detail-main">
      <el-skeleton :loading="!trip" animated>
        <template #default>
          <!-- 行程摘要 -->
          <el-card shadow="never" class="summary-card">
            <div class="summary-grid">
              <div><span>目的地</span><strong>{{ trip?.destination }}</strong></div>
              <div><span>日期</span><strong>{{ trip?.start_date }} · {{ trip?.days }}天</strong></div>
              <div><span>预算</span><strong>¥{{ trip?.budget?.toLocaleString() }}</strong></div>
              <div><span>节奏</span><strong>{{ paceLabel(trip?.pace) }}</strong></div>
            </div>
            <div class="action-row">
              <el-button type="primary" @click="handlePlan" :loading="planning" icon="MagicStick">
                生成方案
              </el-button>
              <el-button @click="showCompare = true" :disabled="plans.length < 1" icon="DataAnalysis">
                方案对比
              </el-button>
              <el-dropdown v-if="plans.length > 0" style="margin-left: 4px;">
                <el-button icon="Download">导出</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item @click="handleExport('markdown')">Markdown</el-dropdown-item>
                    <el-dropdown-item @click="handleExport('ics')">日历 ICS</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </el-card>

          <!-- 个人自由行判断 -->
          <el-card v-if="personalView?.decision_card" shadow="never" class="decision-card">
            <template #header>
              <span><el-icon><DataAnalysis /></el-icon> 方案判断</span>
            </template>
            <div class="decision-grid">
              <div><small>类型</small><strong>{{ personalView.decision_card.label }}</strong></div>
              <div><small>节奏</small><strong>{{ personalView.decision_card.pace_level }}</strong></div>
              <div><small>预算</small><strong>¥{{ personalView.decision_card.total_cost.toLocaleString() }}</strong></div>
              <div><small>活动</small><strong>{{ personalView.decision_card.activity_count }} 个</strong></div>
            </div>
            <p class="decision-copy">{{ personalView.decision_card.best_for }}</p>
            <div class="tag-row">
              <el-tag v-for="item in personalView.decision_card.tradeoffs" :key="item" size="small">
                {{ item }}
              </el-tag>
            </div>
          </el-card>

          <!-- 时间线 -->
          <el-card v-if="activePlan" shadow="never" class="timeline-card">
            <template #header>
              <span><el-icon><Timer /></el-icon> 行程时间线</span>
              <span v-if="verification" style="margin-left: 12px;">
                <el-tag v-if="verification.overall_pass" type="success" size="small">校验通过</el-tag>
                <el-tag v-else type="danger" size="small">校验失败</el-tag>
              </span>
            </template>
            <div v-for="day in activePlanDays" :key="day.day_number" class="day-section">
              <h2>Day {{ day.day_number }} <span>{{ day.theme }}</span></h2>
              <el-timeline>
                <el-timeline-item
                  v-for="seg in day.segments" :key="seg.title"
                  :timestamp="seg.start_time && seg.end_time ? `${seg.start_time}-${seg.end_time}` : ''"
                  :color="segColor(seg.type)"
                >
                  <div class="segment-title">
                    <span><strong>{{ seg.title }}</strong></span>
                    <span v-if="costAmount(seg) > 0" class="segment-cost">
                      {{ formatCost(seg) }}
                    </span>
                  </div>
                  <div class="segment-meta">
                    <el-tag v-for="tag in seg.tags" :key="tag" size="small">
                      {{ tag }}
                    </el-tag>
                    <small v-if="locationText(seg.location)">{{ locationText(seg.location) }}</small>
                  </div>
                  <div v-if="explanationFor(seg)" class="explanation-box">
                    <div v-for="(value, key) in explanationFor(seg)?.sections" :key="key">
                      <strong>{{ key }}：</strong>{{ value }}
                    </div>
                  </div>
                </el-timeline-item>
              </el-timeline>
            </div>
          </el-card>

          <!-- 出发前清单 -->
          <el-card v-if="personalView?.checklist?.length" shadow="never" class="checklist-card">
            <template #header>
              <span><el-icon><List /></el-icon> 出发前清单</span>
            </template>
            <div class="checklist-grid">
              <el-checkbox
                v-for="item in personalView.checklist"
                :key="`${item.category}-${item.title}`"
                v-model="item.done"
                class="checklist-item"
              >
                <el-tag size="small">{{ item.category }}</el-tag>
                <span>{{ item.day_number ? `Day ${item.day_number}：` : '' }}{{ item.title }}</span>
              </el-checkbox>
            </div>
          </el-card>

          <!-- 快捷修改 -->
          <el-card v-if="personalView?.revision_suggestions?.length" shadow="never" class="revision-card">
            <template #header>
              <span><el-icon><MagicStick /></el-icon> 快捷修改</span>
            </template>
            <div class="suggestion-row">
              <el-button
                v-for="item in personalView.revision_suggestions"
                :key="item"
                size="small"
                plain
                :loading="revisionLoading === item"
                @click="handleQuickRevision(item)"
              >
                {{ item }}
              </el-button>
            </div>
          </el-card>

          <!-- 方案列表 -->
          <el-card v-if="plans.length > 0" shadow="never" class="history-card">
            <template #header>
              <span><el-icon><List /></el-icon> 历史方案 ({{ plans.length }})</span>
            </template>
            <el-table :data="plans" stripe size="small">
              <el-table-column label="版本" width="60">
                <template #default="{ row }">v{{ row.version }}</template>
              </el-table-column>
              <el-table-column label="总花费" width="120">
                <template #default="{ row }">¥{{ row.summary?.total_cost?.toLocaleString() || '-' }}</template>
              </el-table-column>
              <el-table-column label="活动数" width="80">
                <template #default="{ row }">{{ row.summary?.activity_count || 0 }}</template>
              </el-table-column>
              <el-table-column label="状态" width="80">
                <template #default="{ row }">
                  <el-tag v-if="row.is_active" type="success" size="small">当前</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作">
                <template #default="{ row }">
                  <el-button type="primary" link size="small" @click="handleSelect(row)">
                    {{ row.is_active ? '已选中' : '选择' }}
                  </el-button>
                  <el-button link size="small" @click="handleExport('markdown', row.plan_id)">
                    导出
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <el-empty v-if="!activePlan && plans.length === 0" description="点击「生成方案」开始规划" />
        </template>
      </el-skeleton>
    </el-main>

    <!-- 方案对比弹窗 -->
    <el-dialog v-model="showCompare" title="方案对比" width="800px" top="5vh">
      <div v-if="compareResult">
        <el-table :data="compareResult.comparison?.diff_matrix || []" border stripe>
          <el-table-column label="维度" prop="dimension" width="120" />
          <el-table-column v-for="(p, i) in compareResult.plans" :key="i" :label="p.label">
            <template #default="{ row }">{{ row.values[i] || '-' }}</template>
          </el-table-column>
        </el-table>
      </div>
      <div style="margin-top: 12px;">
        <el-button @click="handleCompare" :loading="comparing">
          生成 {{ compareCount }} 个方案对比
        </el-button>
        <el-radio-group v-model="compareCount" style="margin-left: 12px;">
          <el-radio-button :value="2">2 方案</el-radio-button>
          <el-radio-button :value="3">3 方案</el-radio-button>
        </el-radio-group>
      </div>
      <div v-if="costEstimate" style="margin-top: 8px; color: #909399; font-size: 13px;">
        预估消耗: {{ costEstimate.estimated_tokens }} tokens, ~${{ costEstimate.estimated_usd }}
      </div>
    </el-dialog>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getTrip, getPersonalTripView, triggerPlan, listPlans, selectPlan, exportTrip, comparePlans, compareCostEstimate, sendChatMessage } from '@/api'
import type { ExplanationCard, PersonalTripView } from '@/types'

const route = useRoute()
const trip = ref<any>(null)
const plans = ref<any[]>([])
const activePlan = ref<any>(null)
const verification = ref<any>(null)
const personalView = ref<PersonalTripView | null>(null)
const planning = ref(false)
const comparing = ref(false)
const showCompare = ref(false)
const compareCount = ref(2)
const compareResult = ref<any>(null)
const costEstimate = ref<any>(null)
const revisionLoading = ref('')

const activePlanDays = computed(() => {
  if (!activePlan.value?.days) return []
  return activePlan.value.days
})

onMounted(loadTrip)

async function loadTrip() {
  const id = route.params.id as string
  try {
    const res = await getTrip(id)
    trip.value = res.data
    // Load plans separately
    const pRes = await listPlans(id)
    plans.value = pRes.data || []
    const active = plans.value.find((p: any) => p.is_active) || plans.value[0]
    if (active) {
      activePlan.value = active.plan_data
      verification.value = active.verification
    }
    await loadPersonalView()
  } catch (e) { console.error(e) }
}

async function loadPersonalView() {
  const id = route.params.id as string
  try {
    const res = await getPersonalTripView(id)
    personalView.value = res.data
  } catch (e) {
    personalView.value = null
  }
}

async function handlePlan() {
  planning.value = true
  const id = route.params.id as string
  try {
    await triggerPlan(id)
    await loadTrip()
  } catch (e) { console.error(e) }
  planning.value = false
}

async function handleSelect(plan: any) {
  const id = route.params.id as string
  await selectPlan(id, plan.plan_id)
  await loadTrip()
}

async function handleExport(format: string, planId?: string) {
  const id = route.params.id as string
  try {
    const res = await exportTrip(id, format, planId)
    if (res.data?.download_url) {
      window.open(res.data.download_url, '_blank')
    }
  } catch (e) { console.error(e) }
}

async function handleCompare() {
  comparing.value = true
  const id = route.params.id as string
  try {
    const est = await compareCostEstimate(id, compareCount.value)
    costEstimate.value = est.data
    const res = await comparePlans(id, compareCount.value)
    compareResult.value = res.data || res
  } catch (e) { console.error(e) }
  comparing.value = false
}

async function handleQuickRevision(message: string) {
  if (!trip.value?.session_id) {
    ElMessage.warning('当前行程缺少会话信息，无法从聊天入口发起修改')
    return
  }
  revisionLoading.value = message
  try {
    const res = await sendChatMessage(message, trip.value.session_id)
    if (res.data?.type === 'plan_result') {
      ElMessage.success('已根据快捷修改更新行程')
      await loadTrip()
    } else {
      ElMessage.info(res.data?.content || '已发送修改请求')
    }
  } catch (e) {
    console.error(e)
    ElMessage.error('快捷修改失败，请稍后再试')
  } finally {
    revisionLoading.value = ''
  }
}

function paceLabel(p: string) {
  return { slow: '慢节奏', moderate: '中节奏', fast: '快节奏' }[p] || p
}

function segColor(type: string) {
  return { activity: '#409eff', meal: '#67c23a', transport: '#e6a23c', accommodation: '#909399' }[type] || '#409eff'
}

function explanationFor(seg: any): ExplanationCard | undefined {
  return personalView.value?.explanations.find((card) =>
    card.segment_id === seg.segment_id || card.segment_id === seg.title
  )
}

function costAmount(seg: any): number {
  const cost = seg?.estimated_cost
  if (typeof cost === 'number') return cost
  if (cost && typeof cost === 'object') return Number(cost.amount || 0)
  return 0
}

function formatCost(seg: any): string {
  const cost = seg?.estimated_cost
  const amount = costAmount(seg)
  const currency = cost && typeof cost === 'object' ? cost.currency : 'CNY'
  const prefix = currency === 'CNY' || !currency ? '¥' : `${currency} `
  return `${prefix}${amount.toLocaleString()}`
}

function locationText(location: any): string {
  if (!location) return ''
  if (typeof location === 'string') return location
  return [location.name, location.city].filter(Boolean).join(' · ')
}
</script>

<style scoped>
.detail-page {
  min-height: 100vh;
  background:
    linear-gradient(90deg, rgba(73, 65, 48, 0.08) 0, rgba(73, 65, 48, 0.08) 1px, transparent 1px) 0 0 / 78px 78px,
    radial-gradient(circle at 12% 10%, rgba(183, 121, 65, 0.18), transparent 28%),
    radial-gradient(circle at 84% 0%, rgba(36, 71, 63, 0.14), transparent 28%),
    var(--rt-bg);
}

.detail-topbar {
  height: 74px;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 0 32px;
  background: rgba(255, 253, 247, 0.8);
  border-bottom: 1px solid var(--rt-border);
  backdrop-filter: blur(22px);
  box-shadow: 0 12px 42px rgba(38, 32, 20, 0.08);
}

.back-button {
  color: var(--rt-muted);
  font-weight: 700;
}

.detail-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.detail-title-icon {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: #fffdf7;
  background: linear-gradient(135deg, var(--rt-accent), var(--rt-primary));
  box-shadow: 0 16px 30px rgba(36, 71, 63, 0.28);
}

.detail-title h1 {
  margin: 0;
  font-family: 'Palatino Linotype', 'Noto Serif SC', serif;
  font-size: 21px;
  line-height: 1.2;
  letter-spacing: 0;
}

.detail-title span {
  color: var(--rt-muted);
  font-size: 12px;
}

.detail-main {
  width: min(1120px, 100%);
  margin: 0 auto;
  padding: 28px;
}

.summary-card,
.decision-card,
.timeline-card,
.checklist-card,
.revision-card,
.history-card {
  margin-bottom: 18px;
  overflow: hidden;
}

.summary-card :deep(.el-card__body) {
  display: grid;
  gap: 18px;
  background:
    radial-gradient(circle at 100% 0%, rgba(183, 121, 65, 0.14), transparent 32%),
    linear-gradient(180deg, rgba(255, 253, 247, 0.96), rgba(255, 253, 247, 0.76));
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.summary-grid div,
.decision-grid div {
  min-height: 86px;
  padding: 15px;
  border: 1px solid var(--rt-border);
  border-radius: 8px;
  background: rgba(255, 253, 247, 0.72);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.78), 0 10px 24px rgba(38, 32, 20, 0.05);
}

.summary-grid span,
.decision-grid small {
  display: block;
  margin-bottom: 9px;
  color: var(--rt-muted);
  font-size: 12px;
  font-weight: 700;
}

.summary-grid strong,
.decision-grid strong {
  display: block;
  color: var(--rt-primary-ink);
  font-family: 'Palatino Linotype', 'Noto Serif SC', serif;
  font-size: 19px;
  line-height: 1.35;
}

.action-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.decision-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.decision-copy {
  margin: 16px 0 12px;
  color: var(--rt-muted);
  line-height: 1.65;
}

.tag-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.suggestion-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.day-section {
  margin-bottom: 28px;
  padding: 16px 16px 4px;
  border: 1px solid rgba(73, 65, 48, 0.12);
  border-radius: 8px;
  background: rgba(255, 253, 247, 0.62);
}

.day-section:last-child {
  margin-bottom: 0;
}

.day-section h2 {
  margin: 0 0 16px;
  color: var(--rt-accent);
  font-family: 'Palatino Linotype', 'Noto Serif SC', serif;
  font-size: 22px;
  letter-spacing: 0;
}

.day-section h2 span {
  color: var(--rt-primary-ink);
  font-size: 17px;
  font-weight: 650;
}

.timeline-card :deep(.el-timeline) {
  padding-left: 4px;
}

.timeline-card :deep(.el-timeline-item__node) {
  box-shadow: 0 0 0 5px rgba(183, 121, 65, 0.12);
}

.timeline-card :deep(.el-timeline-item__tail) {
  border-left-color: rgba(73, 65, 48, 0.16);
}

.timeline-card :deep(.el-timeline-item__timestamp) {
  color: var(--rt-muted);
  font-weight: 700;
}

.timeline-card :deep(.el-timeline-item__content) {
  padding: 12px 14px;
  border: 1px solid rgba(73, 65, 48, 0.12);
  border-radius: 8px;
  background: rgba(255, 253, 247, 0.78);
  box-shadow: 0 12px 26px rgba(38, 32, 20, 0.06);
}

.segment-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.segment-title strong {
  color: var(--rt-primary-ink);
  font-size: 15.5px;
}

.segment-cost {
  color: var(--rt-accent);
  font-size: 13px;
  font-weight: 700;
}

.segment-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 7px;
}

.segment-meta small {
  color: var(--rt-muted);
}

.explanation-box {
  margin-top: 10px;
  padding: 11px 12px;
  border: 1px solid var(--rt-border);
  border-radius: 8px;
  background: rgba(226, 238, 231, 0.5);
  color: var(--rt-muted);
  font-size: 13px;
  line-height: 1.7;
}

.explanation-box strong {
  color: var(--rt-text);
}

.checklist-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.checklist-item {
  min-height: 48px;
  display: flex;
  align-items: center;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--rt-border);
  border-radius: 8px;
  background: rgba(255, 253, 247, 0.7);
}

.checklist-item :deep(.el-checkbox__label) {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--rt-text);
  line-height: 1.45;
}

.history-card :deep(.el-table th.el-table__cell) {
  background: rgba(241, 234, 223, 0.8);
  color: var(--rt-muted);
  font-weight: 700;
}

.history-card :deep(.el-table__row:hover > td.el-table__cell) {
  background: rgba(226, 238, 231, 0.52);
}

@media (max-width: 820px) {
  .detail-topbar {
    padding: 0 16px;
  }

  .detail-main {
    padding: 16px;
  }

  .summary-grid,
  .decision-grid,
  .checklist-grid {
    grid-template-columns: 1fr;
  }
}
</style>
