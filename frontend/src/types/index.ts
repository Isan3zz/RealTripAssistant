export interface Trip {
  trip_id: string
  session_id: string
  destination: string
  start_date: string
  days: number
  budget: number
  pace: string
  status: string
  created_at: string
}

export interface Session {
  session_id: string
  title: string
  status: string
  created_at: string
}

export interface Segment {
  title: string
  type: string
  start_time: string
  end_time: string
  estimated_cost: number | { amount?: number; currency?: string } | null
  tags: string[]
  location: string | { name?: string; city?: string } | null
}

export interface PlanDay {
  day_number: number
  theme: string
  segments: Segment[]
}

export interface PlanData {
  days: PlanDay[]
  pins: any[]
}

export interface Plan {
  plan_id: string
  version: number
  plan_data: PlanData
  verification: any
  is_active: boolean
  summary: PlanSummary
}

export interface PlanSummary {
  total_cost: number
  activity_count: number
  day_count: number
  budget_remaining: number
  avg_daily_cost: number
}

export interface CompareResult {
  comparison_id: string
  status: string
  plans: ComparePlan[]
  comparison: {
    dimensions: string[]
    diff_matrix: DiffRow[]
  }
}

export interface ComparePlan {
  plan_id: string
  label: string
  summary: PlanSummary
}

export interface DiffRow {
  dimension: string
  values: string[]
}

export interface PersonalDecisionCard {
  profile_id: string
  label: string
  best_for: string
  tradeoffs: string[]
  total_cost: number
  activity_count: number
  day_count: number
  pace_level: string
}

export interface ExplanationCard {
  segment_id: string
  day_number: number
  title: string
  type: string
  sections: Record<string, string>
}

export interface ChecklistItem {
  category: string
  day_number: number | null
  title: string
  priority: 'high' | 'medium' | 'low'
  done: boolean
}

export interface PersonalTripView {
  decision_card: PersonalDecisionCard
  explanations: ExplanationCard[]
  checklist: ChecklistItem[]
  revision_suggestions: string[]
}

export interface PlanViewCost {
  amount: number
  currency: string
}

export interface PlanViewLocation {
  name: string
  city: string
}

export interface PlanViewSegment {
  segment_id: string
  type: string
  module: string
  start_time: string
  end_time: string
  time: string
  title: string
  location: PlanViewLocation | null
  estimated_cost: PlanViewCost | null
  tags: string[]
  note: string
  why: string
  attention: string
}

export interface PlanViewDay {
  day_number: number
  title: string
  note: string
  segments: PlanViewSegment[]
}

export interface PlanView {
  schema_version: 'plan.v1'
  title: string
  origin: string
  destination: string
  day_count: number
  budget: PlanViewCost
  total_cost: PlanViewCost
  summary: string[]
  days: PlanViewDay[]
}

export interface ChatResponse {
  type: string
  content: string
  trip_id?: string | null
  plan_summary?: Record<string, unknown> | null
  session_id?: string | null
  plan?: PlanView | null
}

export interface SessionResumeResponse {
  session_id: string
  can_resume: boolean
  title: string
  updated_at?: string | null
  messages?: { role: string; content: string; type?: string | null }[]
  suggested_next_action?: string
  last_trip_id?: string | null
  plan?: PlanView | null
}
