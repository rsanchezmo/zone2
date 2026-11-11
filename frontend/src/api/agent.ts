import { useInfiniteQuery, useQuery, useMutation, useQueryClient, type InfiniteData, type QueryClient } from '@tanstack/react-query';
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

/** A page of the conversation, as the chat panel shows it. */
export interface AgentConversationPage {
  messages: AgentTranscriptItem[];
  /** Writes waiting for a yes, at the conversation's end whatever the page. */
  pending: AgentPendingWrite[];
  /** The cursor for the page before this one; null when this one starts the conversation. */
  older: number | null;
  /** The turns asked for: the page holds that many, or the conversation's first ones when `older` is null. */
  turns: number;
}

const PAGE_TURNS = 20;
// routers/agent.py's cap on a page's turns
const MAX_PAGE_TURNS = 200;

async function conversationPage(conversationId: string, turns: number, before: number | null): Promise<AgentConversationPage> {
  const { data } = await api.get<Omit<AgentConversationPage, 'turns'>>(`/agent/conversations/${conversationId}`, {
    params: before === null ? { turns } : { turns, before },
  });
  return { ...data, turns };
}

/** The conversation's latest turns. Once a newest page is loaded, the new one starts where it
 *  did, so what's on screen keeps its place and the pages loaded before it still follow on. */
async function newestPage(conversationId: string, loaded: AgentConversationPage | undefined): Promise<AgentConversationPage> {
  // The page grows by each turn since it loaded; past the cap it starts over at the latest turns
  const keep = loaded && loaded.turns < MAX_PAGE_TURNS ? loaded : undefined;
  let page = await conversationPage(conversationId, keep?.turns ?? PAGE_TURNS, null);
  if (!keep) return page;
  // The API pages backwards only, and its messages carry no ids to drop an overlap by: the turns
  // that came since fill in one at a time
  while (page.older !== null && page.older > (keep.older ?? 0)) {
    const turn = await conversationPage(conversationId, 1, page.older);
    page = { ...page, messages: [...turn.messages, ...page.messages], older: turn.older, turns: page.turns + 1 };
  }
  return page;
}

/** The conversation, newest page first; `fetchNextPage` loads the page before the oldest loaded.
 *  A refetch fetches the newest page only. */
export function useAgentConversation(conversationId: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: ['agent-conversation', conversationId],
    queryFn: ({ client, queryKey, pageParam }) => {
      const loaded = client.getQueryData<InfiniteData<AgentConversationPage, number | null>>(queryKey);
      if (pageParam === null) return newestPage(conversationId, loaded?.pages[0]);
      // What comes before a cursor never changes (a rewritten message gets a new id), so a refetch
      // keeps the pages already loaded
      const i = loaded?.pageParams.indexOf(pageParam) ?? -1;
      return loaded && i >= 0 ? loaded.pages[i] : conversationPage(conversationId, PAGE_TURNS, pageParam);
    },
    initialPageParam: null,
    getNextPageParam: (page: AgentConversationPage): number | null => page.older,
    enabled,
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
