import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import './index.css'
import App from './App'
import { emitToast } from './hooks/toastBus'

const queryClient = new QueryClient({
  // Surface failures globally — pages mostly render errors as empty states.
  // The toast bus dedupes, so a burst of failing queries yields one toast.
  queryCache: new QueryCache({
    onError: (_error, query) => {
      emitToast(`Failed to load ${String(query.queryKey[0]).replaceAll('-', ' ')}`, 'error')
    },
  }),
  mutationCache: new MutationCache({
    onError: (error) => {
      const detail = isAxiosError(error) ? error.response?.data?.detail : undefined
      emitToast(typeof detail === 'string' ? detail : 'Request failed', 'error')
    },
  }),
  defaultOptions: {
    queries: {
      // Activity data only changes on sync, which explicitly invalidates
      // dependent keys. A longer default avoids needless refetches on
      // remount and focus changes for the 90% of hooks that don't need
      // sub-minute freshness. Hooks that do (sync-status, rate-limits,
      // cache-completeness) override via refetchInterval.
      staleTime: 5 * 60_000,
      gcTime: 30 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
