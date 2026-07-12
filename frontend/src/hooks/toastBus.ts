// Module-level toast bus so non-React code (e.g. the QueryClient's global
// error handlers) can surface toasts through the ToastProvider.

type ToastType = 'success' | 'error';
type ToastListener = (message: string, type: ToastType) => void;

const listeners = new Set<ToastListener>();
const lastEmittedAt = new Map<string, number>();

// A burst of failing queries (e.g. backend down) would otherwise stack an
// identical toast per query.
const DEDUPE_WINDOW_MS = 3000;

export function emitToast(message: string, type: ToastType = 'success'): void {
  const now = Date.now();
  const last = lastEmittedAt.get(message);
  if (last !== undefined && now - last < DEDUPE_WINDOW_MS) return;
  for (const [msg, at] of lastEmittedAt) {
    if (now - at >= DEDUPE_WINDOW_MS) lastEmittedAt.delete(msg);
  }
  lastEmittedAt.set(message, now);
  for (const listener of listeners) listener(message, type);
}

export function subscribeToast(cb: ToastListener): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}
