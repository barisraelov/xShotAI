// Shared helpers for saved-session display.

// Shown when a session has no user-set title (rows created before the
// feature, or a title that never got set). Kept in sync with the backend
// schemas.DEFAULT_SESSION_TITLE.
export const SESSION_TITLE_FALLBACK = 'Training Session'

export const MAX_SESSION_TITLE_LEN = 60

/** A session's display title, falling back when it's null / blank. */
export function sessionTitle(s) {
  const t = (s?.title ?? '').trim()
  return t || SESSION_TITLE_FALLBACK
}
