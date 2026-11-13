// Background jobs: submit, poll progress, fetch result, cancel on abort.
import api from '../services/api';
import i18n from '../i18n';

export type JobKind = 'blink' | 'detect' | 'photometry';

export interface JobProgress {
  id: string; kind: JobKind; status: 'queued' | 'running' | 'done' | 'error' | 'cancelled';
  stage: string; done: number; total: number; elapsed_s: number; queued_s: number;
  error?: { status: number; detail: unknown; code?: string };
  result?: unknown;
}

export class JobError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'JobError';
    this.status = status;
  }
}

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = window.setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => { window.clearTimeout(t); reject(new DOMException('aborted', 'AbortError')); }, { once: true });
  });

function detailText(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail[0] && typeof detail[0] === 'object' && 'msg' in detail[0]) return String((detail[0] as { msg: unknown }).msg);
  return 'Error';
}

/** Run a job to completion. `onProgress` is called on every poll. Aborting cancels the job. */
export async function runJob<T>(
  kind: JobKind,
  params: Record<string, string | number | undefined>,
  onProgress?: (p: JobProgress) => void,
  signal?: AbortSignal,
): Promise<T> {
  const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== ''));
  const start = await api.post('/api/v1/jobs', { kind, params: clean, locale: i18n.language || 'en' }, { signal });
  let job: JobProgress = start.data.data;
  onProgress?.(job);
  const cancel = () => { api.delete(`/api/v1/jobs/${job.id}`).catch(() => undefined); };
  signal?.addEventListener('abort', cancel, { once: true });
  try {
    let delay = 500;
    for (;;) {
      if (job.status === 'done') {
        // Fetch the (possibly large) result once.
        const full = await api.get(`/api/v1/jobs/${job.id}`, { signal, timeout: 120000 });
        return full.data.data.result as T;
      }
      if (job.status === 'error') throw new JobError(detailText(job.error?.detail), job.error?.status ?? 500);
      if (job.status === 'cancelled') throw new DOMException('cancelled', 'AbortError');
      await sleep(delay, signal);
      delay = Math.min(1500, delay + 150);
      const res = await api.get(`/api/v1/jobs/${job.id}`, { params: { include_result: false }, signal });
      job = res.data.data;
      onProgress?.(job);
    }
  } finally {
    signal?.removeEventListener('abort', cancel);
  }
}

export const isAbort = (e: unknown) =>
  (e instanceof DOMException && e.name === 'AbortError') || (typeof e === 'object' && e !== null && (e as { code?: string }).code === 'ERR_CANCELED');
