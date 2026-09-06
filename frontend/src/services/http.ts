/**
 * Single place that decides where the API lives.
 *
 * By default requests are relative, so Vite's dev proxy (vite.config.ts) and a
 * production build served by the backend both work without changes. Set
 * VITE_API_BASE only when the backend runs somewhere else, e.g.
 * VITE_API_BASE=http://127.0.0.1:8095
 *
 * Do not hardcode hostnames in components -- doing so broke every AI Studio
 * call whenever the backend moved off port 8000.
 */
export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '');

/** Default ceiling for a single request; a hung backend should not spin forever. */
export const DEFAULT_TIMEOUT_MS = 60_000;

export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

/** fetch() against the API base, with a timeout applied unless the caller sets one. */
export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(apiUrl(path), {
    ...init,
    signal: init.signal ?? AbortSignal.timeout(DEFAULT_TIMEOUT_MS),
  });
}
