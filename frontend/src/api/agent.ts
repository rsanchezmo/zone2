import { useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';
import api from './client';
import { refreshPages } from './invalidation';

export interface AgentUsageTotals {
  runs: number;
  conversations: number;
  requests: number;
  tool_calls: number;
  /** Cached tokens included. */
  input_tokens: number;
  cache_read_tokens: number;
  output_tokens: number;
  cost_usd: number;
  /** Runs on a model without a known price: their cost is missing from `cost_usd`. */
  unpriced_runs: number;
}

export interface AgentUsage {
  model: string;
  /** Counting down from the last top-up entered on the Profile page; null until one is. */
  credit: { added_usd: number; since: string; spent_usd: number; left_usd: number } | null;
  all_time: AgentUsageTotals;
  this_month: AgentUsageTotals;
  /** Only days the agent ran, oldest first. */
  days: { date: string; runs: number; input_tokens: number; output_tokens: number; cost_usd: number }[];
  models: { model: string; runs: number; input_tokens: number; output_tokens: number; cost_usd: number }[];
}

export function useAgentUsage(days: number) {
  return useQuery<AgentUsage>({
    queryKey: ['agent-usage', days],
    queryFn: () => api.get('/agent/usage', { params: { days } }).then(r => r.data),
    staleTime: 1000 * 60 * 5,
  });
}

export interface AgentStatus {
  available: boolean;
  model: string;
  /** The coach's reviews of new activities since the chat was last opened. */
  unread: number;
}

export interface AgentModelOption { id: string; name: string; input_usd: number | null; output_usd: number | null }

export interface AgentSettings { model: string; models: AgentModelOption[] }

export function useAgentSettings() {
  return useQuery<AgentSettings>({
    queryKey: ['agent-settings'],
    queryFn: () => api.get('/agent/settings').then(r => r.data),
    staleTime: 1000 * 60 * 60,
  });
}

export function useSetAgentSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (update: { model?: string; credit_usd?: number }) =>
      api.put<AgentSettings>('/agent/settings', update).then(r => r.data),
    onSuccess: data => {
      qc.setQueryData(['agent-settings'], data);
      qc.invalidateQueries({ queryKey: ['agent-status'] });
      qc.invalidateQueries({ queryKey: ['agent-usage'] });
    },
  });
}

export interface AgentPendingWrite { id: string; tool: string; args: Record<string, unknown> }

export type AgentTranscriptItem =
  | { role: 'user'; text: string }
  | { role: 'agent'; text: string }
  | { role: 'tool'; tool: string }
  /** A new session began here, after a pause: the coach started fresh from your notes and log. */
  | { role: 'session'; at: string }
  /** The coach wrote on its own here, e.g. "After your run: Test 5k" once a sync brought it in. */
  | { role: 'event'; text: string; at: string };

export interface AgentTurn {
  conversation_id: string;
  reply: string | null;
  tools: { tool: string; args: Record<string, unknown> }[];
  /** Writes waiting for a yes or no. */
  pending: AgentPendingWrite[];
  /** A write or a note ran, so pages showing that data refresh. */
  changed: boolean;
  usage: { input_tokens: number; output_tokens: number; cost_usd: number | null };
}

export function useAgentStatus() {
  return useQuery<AgentStatus>({
    queryKey: ['agent-status'],
    queryFn: () => api.get('/agent/status').then(r => r.data),
    // Often enough that a review written after a sync shows up on the robot
    refetchInterval: 1000 * 60,
  });
}

/** The chat is open: the coach's reviews so far are read. */
export function useMarkCoachSeen() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post('/agent/seen').then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-status'] }),
  });
}

/** The chat opened: stale data starts syncing and the coach loads while the athlete types. */
export function useOpenCoach() {
  return useMutation({
    mutationFn: () => api.post('/agent/open').then(r => r.data),
  });
}

export function useAgentConversation(conversationId: string | null) {
  return useQuery<{ messages: AgentTranscriptItem[]; pending: AgentPendingWrite[] }>({
    queryKey: ['agent-conversation', conversationId],
    queryFn: () => api.get(`/agent/conversations/${conversationId}`).then(r => r.data),
    enabled: conversationId != null,
    staleTime: Infinity,
  });
}

export type AgentStreamEvent =
  | { type: 'thinking' }
  | { type: 'tool'; tool: string; args: Record<string, unknown> }
  | { type: 'tool_done'; tool: string }
  | { type: 'text'; delta: string }
  | { type: 'open'; path: string }
  | { type: 'done'; turn: AgentTurn }
  | { type: 'error'; detail: string };

export function refreshAfterAgentTurn(qc: QueryClient, turn: AgentTurn) {
  qc.invalidateQueries({ queryKey: ['agent-usage'] });
  if (turn.changed) refreshPages(qc);
}

/** One agent turn, streamed as it runs: `onEvent` sees each step (tools, the reply as it is
 *  written), and the promise resolves with the whole turn. A message, or answers to pending writes. */
export async function streamAgentTurn(
  path: 'chat' | 'approve',
  body: { conversation_id: string; page: string; message?: string; approvals?: Record<string, boolean> },
  onEvent: (event: AgentStreamEvent) => void,
): Promise<AgentTurn> {
  const res = await fetch(`/api/agent/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const detail = await res.json().then(d => d?.detail).catch(() => null);
    throw new Error(typeof detail === 'string' ? detail : `The coach didn't answer (${res.status})`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let turn: AgentTurn | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const data = buffer.slice(0, cut).split('\n').filter(l => l.startsWith('data: ')).map(l => l.slice(6)).join('\n');
      buffer = buffer.slice(cut + 2);
      if (!data) continue;
      const event = JSON.parse(data) as AgentStreamEvent;
      if (event.type === 'error') throw new Error(event.detail);
      if (event.type === 'done') turn = event.turn;
      onEvent(event);
    }
  }
  if (!turn) throw new Error('The coach stopped before it finished.');
  return turn;
}
