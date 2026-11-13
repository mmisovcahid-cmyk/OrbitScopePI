import { useEffect, useState } from 'react';
import { systemService } from '../services';

/**
 * Is the backend's internet connection up? (Raspberry Pi demos often run without one.)
 * One shared poll of /system/status for the whole app; components subscribe with useNetwork().
 * `online` is null until the first answer, and stays null when the backend itself is unreachable.
 */
export interface NetworkState {
  online: boolean | null;
}

const POLL_MS = 30_000;
let state: NetworkState = { online: null };
const listeners = new Set<(s: NetworkState) => void>();
let timer: ReturnType<typeof setInterval> | null = null;

async function poll() {
  try {
    const res = await systemService.status();
    const online = res.data?.data?.components?.network?.online;
    state = { online: typeof online === 'boolean' ? online : null };
  } catch {
    state = { online: null };
  }
  listeners.forEach((l) => l(state));
}

export function useNetwork(): NetworkState {
  const [s, setS] = useState(state);
  useEffect(() => {
    listeners.add(setS);
    if (!timer) {
      void poll();
      timer = setInterval(poll, POLL_MS);
    }
    return () => {
      listeners.delete(setS);
      if (listeners.size === 0 && timer) {
        clearInterval(timer);
        timer = null;
      }
    };
  }, []);
  return s;
}

/** "2026-11-14T08:00:00Z" -> local date + time for the "cached on" labels. */
export function formatSnapshot(iso: string, lang: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(lang === 'az' ? 'az-Latn-AZ' : 'en-GB', { dateStyle: 'medium', timeStyle: 'short' });
}
