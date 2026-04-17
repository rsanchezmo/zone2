import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export default class RootErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('App render crash:', error, info.componentStack)
  }

  handleReload = () => {
    window.location.reload()
  }

  handleTryAgain = () => {
    this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-surface-900 text-gray-200">
        <div className="max-w-lg w-full rounded-xl border border-surface-600 bg-surface-800 p-6 shadow-2xl">
          <h2 className="text-lg font-semibold text-gray-100 mb-1">
            Something went wrong
          </h2>
          <p className="text-sm text-gray-400 mb-4">
            An unexpected error crashed the page. You can try recovering without losing your place, or reload from scratch.
          </p>
          <pre className="text-xs text-gray-500 bg-surface-900 border border-surface-700 p-3 rounded-lg overflow-auto max-h-48 whitespace-pre-wrap mb-4">
            {error.message}
          </pre>
          <div className="flex gap-2">
            <button
              onClick={this.handleTryAgain}
              className="px-4 py-2 bg-surface-700 border border-surface-600 rounded-lg text-sm hover:bg-surface-600 transition-colors"
            >
              Try again
            </button>
            <button
              onClick={this.handleReload}
              className="px-4 py-2 bg-blue-500/20 border border-blue-500/40 text-blue-200 rounded-lg text-sm hover:bg-blue-500/30 transition-colors"
            >
              Reload
            </button>
          </div>
        </div>
      </div>
    )
  }
}
