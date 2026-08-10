const BASE = '/api'

export interface LedgerEntry {
  entry_id: string
  entry_type: string
  agent_id: string
  content_raw: string
  content: Record<string, unknown> | null
  content_type: string
  source_id: string
  correlation_id: string
  entry_hash: string
  previous_hash: string
  chain_position: number
  written_ts: number
  input_hash: string
  writer_signature: string
  signer_key_reference: string
  attestation_report: string
  hash_version: string
}

export interface EntryPage {
  entries: LedgerEntry[]
  next_page_token: string
  total_count: number
}

export interface ChainInfo {
  entry_type: string
  count: number
  source: string
  entries: LedgerEntry[]
}

export interface VerifyResult {
  entry_type: string
  chain_valid: boolean
  entries_checked: number
  failure_reason: string
}

export interface Summary {
  total_entries: number
  sources: Record<string, number>
  chain_types: number
  correlation_ids: number
  cross_system_correlations: number
}

export interface DriftGap {
  entry_id: string
  correlation_id: string
  agent_id: string
  source_id: string
  entry_type: string
  detail: string
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json()
}

export const api = {
  entries: async (params?: Record<string, string>) => {
    const MAX_PAGES = 100
    const entries: LedgerEntry[] = []
    const seenTokens = new Set<string>()
    let pageToken = ''
    let pages = 0
    do {
      const query = new URLSearchParams({ ...params, page_size: '1000' })
      if (pageToken) query.set('page_token', pageToken)
      const page = await get<EntryPage>(`/entries?${query.toString()}`)
      entries.push(...page.entries)
      pageToken = page.next_page_token
      if (pageToken && seenTokens.has(pageToken)) {
        throw new Error('API returned a repeated pagination token')
      }
      seenTokens.add(pageToken)
      pages++
    } while (pageToken && pages < MAX_PAGES)
    return entries
  },
  summary: () => get<Summary>('/summary'),
  chains: () => get<ChainInfo[]>('/chains'),
  verify: () => get<{ all_valid: boolean; chains: VerifyResult[] }>('/verify'),
  verifyChain: (type: string) => get<VerifyResult>(`/verify/${type}`),
  timeline: () => get<{ entries: LedgerEntry[]; correlations: Record<string, string[]> }>('/timeline'),
  drift: () => get<{ gaps: DriftGap[]; total_denials: number; total_scope_evals: number }>('/drift'),
}
