import { Component, type ReactNode } from 'react'

interface Props {
  // Clears a caught error when it changes, so navigating to another
  // page recovers without a manual reset.
  resetKey: string
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * Catches page render crashes while keeping the surrounding shell
 * (dock, mobile nav) alive — the root boundary would blank everything.
 */
export default class PageErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Page render crash:', error, info.componentStack)
  }

  componentDidUpdate(prevProps: Props) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  handleTryAgain = () => {
    this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div className="flex items-center justify-center py-16">
        <div className="max-w-lg w-full rounded-xl border border-surface-600 bg-surface-800 p-6 shadow-2xl">
          <h2 className="text-lg font-semibold text-gray-100 mb-1">
            This page crashed
          </h2>
          <p className="text-sm text-gray-400 mb-4">
            The rest of the app is still working — navigate elsewhere or try again.
          </p>
          <pre className="text-xs text-gray-500 bg-surface-900 border border-surface-700 p-3 rounded-lg overflow-auto max-h-48 whitespace-pre-wrap mb-4">
            {error.message}
          </pre>
          <button
            onClick={this.handleTryAgain}
            className="px-4 py-2 bg-surface-700 border border-surface-600 rounded-lg text-sm hover:bg-surface-600 transition-colors"
          >
            Try again
          </button>
        </div>
      </div>
    )
  }
}
