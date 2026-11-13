import api from './api';
import i18n from '../i18n';

const locale = () => i18n.language || 'en';

const TOKEN_KEY = 'orbitscope.reviewToken';
function readToken(): string {
  try { return localStorage.getItem(TOKEN_KEY) ?? ''; } catch { return ''; }
}

/** PATCH a review. A public server may require the team's review token (HTTP 403): ask once, remember it. */
async function reviewWithToken(id: string, status: string, note?: string) {
  const send = (token: string) => api.patch(`/api/v1/spherex/candidates/${encodeURIComponent(id)}`, { status, note }, {
    params: { locale: locale() }, headers: token ? { 'X-Review-Token': token } : undefined,
  });
  try {
    return await send(readToken());
  } catch (err) {
    const e = err as { response?: { status?: number } };
    if (e.response?.status !== 403) throw err;
    const token = window.prompt(i18n.t('detect.reviewTokenPrompt')) ?? '';
    if (!token) throw err;
    try { localStorage.setItem(TOKEN_KEY, token); } catch { /* storage unavailable */ }
    return send(token);
  }
}

export const catalogService = {
  search: (query: string) =>
    api.get('/api/v1/catalog/search', { params: { query, locale: locale() } }),
  getObject: (designation: string) =>
    api.get(`/api/v1/catalog/object/${encodeURIComponent(designation)}`, { params: { locale: locale() } }),
  getEphemeris: (target: string, days = 7) =>
    api.get('/api/v1/catalog/ephemeris', { params: { target, days, locale: locale() }, timeout: 90000 }),
  getNearby: (ra: number, dec: number, radius = 60) =>
    api.get('/api/v1/catalog/nearby', { params: { ra, dec, radius_arcsec: radius, locale: locale() }, timeout: 120000 }),
  /** Known asteroids/comets in a field (radius in degrees) at a UTC time (JPL SB Ident, ~20 s). */
  getField: (ra: number, dec: number, radiusDeg: number, time?: string) =>
    api.get('/api/v1/catalog/nearby', { params: { ra, dec, radius: radiusDeg, time, locale: locale() }, timeout: 120000 }),
};

export const planetxService = {
  getEvidence: () => api.get('/api/v1/planetx/evidence', { params: { locale: locale() } }),
  getTNOs: () => api.get('/api/v1/planetx/tnos', { params: { locale: locale() } }),
  getRegions: () => api.get('/api/v1/planetx/regions', { params: { locale: locale() } }),
  getClustering: () => api.get('/api/v1/planetx/clustering', { params: { locale: locale() }, timeout: 120000 }),
};

// Real SPHEREx data. The first request for a field downloads cutouts from IRSA (can take 1-2 min).
export const spherexService = {
  targets: () => api.get('/api/v1/spherex/targets'),
  resolve: (q: string) => api.get('/api/v1/spherex/resolve', { params: { q, locale: locale() } }),
  coverage: (ra: number, dec: number) =>
    api.get('/api/v1/spherex/coverage', { params: { ra, dec, locale: locale() }, timeout: 240000 }),
  blink: (params: Record<string, string | number>, signal?: AbortSignal) =>
    api.get('/api/v1/spherex/blink', { params: { ...params, locale: locale() }, timeout: 300000, signal }),
  overlay: (ra: number, dec: number, fov: number, catalog: 'gaia' | 'catwise') =>
    api.get('/api/v1/spherex/overlay', { params: { ra, dec, fov, catalog, locale: locale() }, timeout: 120000 }),
  photometry: (params: Record<string, string | number>, signal?: AbortSignal) =>
    api.get('/api/v1/spherex/photometry', { params: { ...params, locale: locale() }, timeout: 600000, signal }),
  detect: (params: Record<string, string | number>, signal?: AbortSignal) =>
    api.get('/api/v1/spherex/detect', { params: { ...params, locale: locale() }, timeout: 600000, signal }),
  candidates: (status?: string) =>
    api.get('/api/v1/spherex/candidates', { params: { status: status || undefined, limit: 200 } }),
  candidate: (id: string) => api.get(`/api/v1/spherex/candidates/${encodeURIComponent(id)}`, { params: { locale: locale() } }),
  overview: () => api.get('/api/v1/spherex/overview', { timeout: 30000 }),
  review: (id: string, status: string, note?: string) => reviewWithToken(id, status, note),
  exportUrl: (id: string) => `${api.defaults.baseURL}/api/v1/spherex/candidates/${encodeURIComponent(id)}/export`,
  gifUrl: (params: Record<string, string | number>) => {
    const qs = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();
    return `${api.defaults.baseURL}/api/v1/spherex/blink.gif?${qs}`;
  },
};

export const groundService = {
  status: () => api.get('/api/v1/ground/status', { params: { locale: locale() } }),
  sessions: () => api.get('/api/v1/ground/sessions', { params: { locale: locale() } }),
  session: (id: string) => api.get(`/api/v1/ground/sessions/${encodeURIComponent(id)}`, { params: { locale: locale() } }),
  upload: (files: File[], label: string) => {
    const form = new FormData();
    files.forEach((f) => form.append('files', f));
    form.append('label', label);
    form.append('locale', locale());
    return api.post('/api/v1/ground/sessions', form, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 600000 });
  },
  analyze: (id: string) =>
    api.post(`/api/v1/ground/sessions/${encodeURIComponent(id)}/analyze`, null, { params: { locale: locale() }, timeout: 600000 }),
  capture: (frames: number, exposure_s: number) =>
    api.post('/api/v1/ground/capture', { frames, exposure_s, locale: locale() }, { timeout: 900000 }),
};

export const systemService = {
  health: () => api.get('/api/v1/system/health'),
  status: () => api.get('/api/v1/system/status'),
  dataSources: () => api.get('/api/v1/system/datasources'),
  kiosk: () => api.get('/api/v1/system/kiosk'),
};
