import { apiFetch } from './http';

// Thin JSON helpers over apiFetch. A non-2xx response becomes an Error whose
// message carries the backend's `detail`, so pages can show it in a toast
// instead of guessing.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) {
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (body && typeof body.detail === 'string') detail = body.detail;
    else if (body && typeof body.message === 'string') detail = body.message;
  } catch {
    // no JSON body
  }
  throw new ApiError(res.status, detail);
}

export async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  return parse<T>(await apiFetch(path, init));
}

export async function postJson<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  return parse<T>(
    await apiFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
      ...init,
    }),
  );
}

export function describeError(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof DOMException && err.name === 'TimeoutError') return 'The backend did not answer in time.';
  if (err instanceof TypeError) return 'Could not reach the Studio backend.';
  if (err instanceof Error) return err.message;
  return String(err);
}
