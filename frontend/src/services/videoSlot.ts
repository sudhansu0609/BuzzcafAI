/**
 * One video at a time (2026-10-26). The backend refuses a second video while
 * one is being made with 409 `{detail: {code: "video_running", ...}}`
 * (backend app/services/video_slot.py). This wraps `window.fetch` once, so
 * every page's start button -- whichever helper it uses -- gets the same
 * answer: the pop-up asks, and the caller's promise resolves with the
 * outcome of the choice ("start after it" resends the request with
 * `when_free=1`; cancel hands back the original 409).
 */
import { apiUrl } from './http';

export interface ActiveVideo {
  project_id?: string;
  title?: string;
  brand?: string;
  what?: string;
  doing?: string | null;
  progress_pct?: number;
  queue_item_id?: string;
  can_pause?: boolean;
}

export interface VideoBusy {
  code: 'video_running';
  message: string;
  active: ActiveVideo;
}

export type VideoBusyChoice = 'after' | 'pause' | 'cancel';
type Handler = (busy: VideoBusy) => Promise<VideoBusyChoice>;

let handler: Handler | null = null;
let installed = false;

/** The pop-up registers itself here; with none mounted a 409 passes through untouched. */
export function setVideoBusyHandler(next: Handler | null): void {
  handler = next;
}

function withWhenFree(url: string): string {
  return url + (url.includes('?') ? '&' : '?') + 'when_free=1';
}

export function installVideoSlotFetch(): void {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  const original = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const res = await original(input, init);
    if (res.status !== 409 || !handler || input instanceof Request) return res;
    let busy: VideoBusy | undefined;
    try {
      const body = await res.clone().json() as { detail?: VideoBusy };
      busy = body?.detail;
    } catch {
      return res;
    }
    if (!busy || busy.code !== 'video_running') return res;
    const choice = await handler(busy);
    if (choice === 'cancel') return res;
    if (choice === 'pause' && busy.active.queue_item_id) {
      await original(apiUrl(`/api/produce/queue/${busy.active.queue_item_id}/pause`), { method: 'POST' });
    }
    // The first request's timeout may have run out while the pop-up waited.
    return original(withWhenFree(String(input)), { ...init, signal: undefined });
  };
}
