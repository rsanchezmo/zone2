import '@tanstack/react-query'

declare module '@tanstack/react-query' {
  interface Register {
    // inlineError: the page shows the query's error itself, no global toast
    queryMeta: { inlineError?: boolean }
  }
}
