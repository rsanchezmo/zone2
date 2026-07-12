/** Expand/collapse arrows for the map fullscreen toggle. */
export function FullscreenIcon({ expanded }: { expanded: boolean }) {
  return expanded ? (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 2v4H2M10 14v-4h4M14 2l-4 4M2 14l4-4" />
    </svg>
  ) : (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 6V2h4M14 10v4h-4M2 2l4 4M14 14l-4-4" />
    </svg>
  )
}
