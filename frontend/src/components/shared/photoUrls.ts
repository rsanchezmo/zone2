export interface LightboxPhoto {
  unique_id: string
  urls: Record<string, string>
  caption?: string | null
}

/** Strava stores a single size per photo (fetched at 600px); the size-key
 *  preference just degrades gracefully if that ever changes. */
export function photoThumbUrl(photo: { urls: Record<string, string> }): string {
  const urls = photo.urls || {}
  return urls['200'] || urls['100'] || urls['400'] || urls['600'] || Object.values(urls)[0]
}

export function photoFullUrl(photo: { urls: Record<string, string> }): string {
  const urls = photo.urls || {}
  return urls['600'] || urls['400'] || urls['200'] || urls['100'] || Object.values(urls)[0]
}
