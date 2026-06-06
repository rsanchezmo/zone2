import { useCallback, useEffect, useState, type ReactNode } from 'react'
import clsx from 'clsx'
import { useTheme } from './useTheme'
import { ToastContext, type Toast, type ToastType } from './toastContext'

let nextId = 0

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const addToast = useCallback((message: string, type: ToastType = 'info') => {
    const id = ++nextId
    setToasts(t => [...t, { id, message, type }])
    setTimeout(() => {
      setToasts(t => t.filter(toast => toast.id !== id))
    }, 3500)
  }, [])

  return (
    <ToastContext.Provider value={{ toast: addToast }}>
      {children}
      <div className="fixed bottom-6 right-6 z-[100] flex flex-col gap-2 pointer-events-none">
        {toasts.map(t => (
          <ToastItem key={t.id} toast={t} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

function ToastItem({ toast }: { toast: Toast }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const frame = requestAnimationFrame(() => setVisible(true))
    return () => cancelAnimationFrame(frame)
  }, [])

  return (
    <div
      className={clsx(
        'px-4 py-2.5 rounded-xl text-sm font-medium shadow-lg backdrop-blur-xl border pointer-events-auto',
        'transition-all duration-300 ease-out',
        visible ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-8',
        toast.type === 'success' && (isLight
          ? 'bg-green-50/90 text-green-700 border-green-200'
          : 'bg-green-500/10 text-green-400 border-green-500/20'),
        toast.type === 'error' && (isLight
          ? 'bg-red-50/90 text-red-700 border-red-200'
          : 'bg-red-500/10 text-red-400 border-red-500/20'),
        toast.type === 'info' && (isLight
          ? 'bg-blue-50/90 text-blue-700 border-blue-200'
          : 'bg-blue-500/10 text-blue-400 border-blue-500/20'),
      )}
    >
      {toast.message}
    </div>
  )
}
