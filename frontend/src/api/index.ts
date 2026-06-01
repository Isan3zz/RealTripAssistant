import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    console.error('API Error:', err.response?.data || err.message)
    return Promise.reject(err)
  }
)

export default api

// ── 健康检查 ──
export const healthCheck = () => api.get('/health')

// ── 会话 ──
export const createSession = (userId: string, title?: string) =>
  api.post('/sessions', { user_id: userId, title: title || '新建行程' })

export const listSessions = (userId: string) =>
  api.get('/sessions', { params: { user_id: userId } })

export const resumeSession = (sessionId: string) =>
  api.get(`/sessions/${sessionId}/resume`)

export const listRecentSessions = (limit = 20) =>
  api.get('/sessions/recent', { params: { limit } })

export const deleteSession = (sessionId: string) =>
  api.delete(`/sessions/${sessionId}`)

// ── 行程 ──
export const createTrip = (data: any) => api.post('/trips', data)

export const listTrips = (params?: { session_id?: string; status?: string }) =>
  api.get('/trips', { params })

export const getTrip = (tripId: string) =>
  api.get(`/trips/${tripId}`)

export const getPersonalTripView = (tripId: string) =>
  api.get(`/trips/${tripId}/personal`)

export const sendChatMessage = (message: string, sessionId?: string) =>
  api.post('/chat', { message, session_id: sessionId })

export const deleteTrip = (tripId: string) =>
  api.delete(`/trips/${tripId}`)

// ── 规划 ──
export const triggerPlan = (tripId: string, mode = 'generate') =>
  api.post(`/trips/${tripId}/plan`, { mode })

export const listPlans = (tripId: string) =>
  api.get(`/trips/${tripId}/plans`)

export const getPlan = (tripId: string, planId: string) =>
  api.get(`/trips/${tripId}/plans/${planId}`)

export const selectPlan = (tripId: string, planId: string) =>
  api.post(`/trips/${tripId}/select-plan`, { plan_id: planId })

// ── 方案对比 ──
export const compareCostEstimate = (tripId: string, count = 2) =>
  api.post(`/trips/${tripId}/compare/cost-estimate`, { count })

export const comparePlans = (tripId: string, count = 2, dimensions = ['budget', 'pace', 'diversity']) =>
  api.post(`/trips/${tripId}/compare`, { count, dimensions })

// ── 导出 ──
export const exportTrip = (tripId: string, format = 'markdown', planId?: string) =>
  api.post(`/trips/${tripId}/export`, { format, plan_id: planId })
