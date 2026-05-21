/** ─── NexusTrader — AI Copilot Types ───────────────────────────────────────────────── */

export type AIMessageRole = 'user' | 'assistant' | 'system'

/** Actiune propusa de AI in raspuns, parsata din blocul <action>...</action> */
export interface AIAction {
  type:
    | 'place_order'
    | 'close_position'
    | 'close_all'
    | 'cancel_all'
    | 'emergency_stop'
    | 'resume_trading'
    | 'patch_settings'
  label: string
  description: string
  params: Record<string, unknown>
}

export interface AIMessage {
  id: string
  role: AIMessageRole
  /** Continut text pur (fara blocurile <action>) */
  content: string
  /** Actiuni propuse parsate din mesaj */
  actions?: AIAction[]
  /** Timestamp ISO */
  timestamp: string
  /** true cat timp streamingul e activ pentru acest mesaj */
  streaming?: boolean
}

export interface AIStatus {
  enabled: boolean
  provider: 'groq' | 'openai' | 'none'
  model: string
  has_groq: boolean
  has_openai: boolean
}

export interface AIExecuteResult {
  success: boolean
  action: string
  result?: unknown
  error?: string
}
