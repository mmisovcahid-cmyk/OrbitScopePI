/**
 * Kiosk mode for the Raspberry Pi's own screen. The kiosk browser opens /?kiosk=1 (see
 * deploy/pi/kiosk.sh); the flag is remembered for the session so in-app navigation keeps it,
 * and /?kiosk=0 turns it off. In kiosk mode the <html> element gets the `kiosk` class: the UI
 * scales with the screen size (from 800x480 panels to 4K TVs) and touch targets grow when the
 * screen is a touchscreen. Nothing changes for normal visitors.
 */
const KEY = 'orbitscope.kiosk';

function readFlag(): boolean {
  try {
    const q = new URLSearchParams(window.location.search).get('kiosk');
    if (q === '1' || q === 'true') sessionStorage.setItem(KEY, '1');
    if (q === '0' || q === 'false') sessionStorage.removeItem(KEY);
    return sessionStorage.getItem(KEY) === '1';
  } catch {
    return new URLSearchParams(window.location.search).get('kiosk') === '1';
  }
}

export const isKiosk: boolean = typeof window !== 'undefined' && readFlag();

export function applyKioskClass(): void {
  if (!isKiosk) return;
  const root = document.documentElement;
  root.classList.add('kiosk');
  const touch = window.matchMedia?.('(pointer: coarse)').matches || navigator.maxTouchPoints > 0;
  if (touch) root.classList.add('touch');
}
