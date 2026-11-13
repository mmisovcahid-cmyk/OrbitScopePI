// Helpers for the real-data SPHEREx blink viewer: types, decoding, stretching, colour maps, WCS.

export interface BlinkMember {
  obs_id: string;
  collection: string;
  detector: number;
  mjd: number;
  date: string;
  wavelength_um: [number, number];
  wavelength_center_um: number | null;
  url: string;
}

export interface BlinkFrame {
  index: number;
  mjd: number;
  date: string;
  date_start: string;
  date_end: string;
  n_frames: number;
  detectors: number[];
  wavelength_um: [number, number] | null;
  members: BlinkMember[];
  flags: Record<string, number>;
  masked_fraction: number;
  target_px: [number, number] | null;
  data: string;
  mask: string;
}

export interface BlinkResult {
  target: {
    ra: number; dec: number; pmra: number | null; pmdec: number | null; ref_epoch: number;
    center_ra: number; center_dec: number; name: string | null; resolver: string | null; note?: string | null;
  };
  grid: { width: number; height: number; pixscale_arcsec: number; fov_deg: number; crpix: [number, number]; ra: number; dec: number };
  coverage: {
    total_frames: number; by_detector: Record<string, number>; collections: string[]; n_epochs: number;
    epochs: { start: string; end: string; n_frames: number }[]; date_min: string | null; date_max: string | null;
  };
  mode: 'epoch' | 'frames' | 'pass';
  pass_index?: number | null;
  detectors: number[];
  frames: BlinkFrame[];
  stretch_hint: { vmin: number; vmax: number };
  units: string;
  source: string;
  is_simulated: boolean;
  elapsed_s: number;
}

export interface DecodedFrame {
  meta: BlinkFrame;
  values: Float32Array; // row 0 = south edge
  mask: Uint8Array; // 1 = flagged / filled pixel
}

export interface BlinkQuery {
  target?: string;
  ra?: number;
  dec?: number;
  fov: number;
  detector: string;
  mode: 'epoch' | 'frames' | 'pass';
  per_epoch: number;
  max_frames: number;
  pass_index?: number;
  /** Wavelength band "lo-hi" in um, applied per exposure (SPHEREx LVF), e.g. "3.2-3.45". */
  band?: string;
}

/** Spectral features worth isolating with SPHEREx's 102 channels. */
export const BAND_PRESETS: { id: string; key: string }[] = [
  { id: '1.3-1.5', key: 'h2o' },
  { id: '2.0-2.4', key: 'k' },
  { id: '3.2-3.45', key: 'ch4' },
  { id: '4.4-5.0', key: 'co' },
];

export function parseBand(b?: string): [number, number] | null {
  const m = /^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)$/.exec(b ?? '');
  if (!m) return null;
  const lo = Number(m[1]); const hi = Number(m[2]);
  return lo >= 0.7 && hi <= 5.1 && lo < hi ? [lo, hi] : null;
}

export const DEFAULT_QUERY: BlinkQuery = { fov: 0.1, detector: '3', mode: 'epoch', per_epoch: 4, max_frames: 16 };

export const DETECTOR_INFO: Record<string, string> = {
  '1': '0.75–1.11 µm',
  '2': '1.10–1.65 µm',
  '3': '1.63–2.42 µm',
  '4': '2.42–3.82 µm',
  '5': '3.82–4.42 µm',
  '6': '4.41–5.01 µm',
  all: '0.75–5.0 µm',
};

export function decodeFrames(res: BlinkResult): DecodedFrame[] {
  const n = res.grid.width * res.grid.height;
  return res.frames.map((f) => {
    const raw = atob(f.data);
    const buf = new ArrayBuffer(raw.length);
    const u8 = new Uint8Array(buf);
    for (let i = 0; i < raw.length; i++) u8[i] = raw.charCodeAt(i);
    const values = new Float32Array(buf);
    const packed = atob(f.mask);
    const mask = new Uint8Array(n);
    for (let i = 0; i < n; i++) {
      const byte = packed.charCodeAt(i >> 3);
      mask[i] = (byte >> (7 - (i & 7))) & 1;
    }
    return { meta: f, values, mask };
  });
}

/** Percentile over finite values (sub-sampled for speed). */
export function percentiles(arrays: Float32Array[], ps: number[], abs = false): number[] {
  const sample: number[] = [];
  const total = arrays.reduce((s, a) => s + a.length, 0);
  const step = Math.max(1, Math.floor(total / 60000));
  let k = 0;
  for (const a of arrays) {
    for (let i = 0; i < a.length; i++, k++) {
      if (k % step) continue;
      const v = a[i];
      if (Number.isFinite(v)) sample.push(abs ? Math.abs(v) : v);
    }
  }
  if (!sample.length) return ps.map(() => 0);
  sample.sort((x, y) => x - y);
  return ps.map((p) => sample[Math.min(sample.length - 1, Math.max(0, Math.round((p / 100) * (sample.length - 1))))]);
}

export type StretchKind = 'asinh' | 'linear' | 'log' | 'sqrt';
export type ColorMapKind = 'gray' | 'inferno' | 'viridis' | 'invert';

export function stretchValue(x: number, kind: StretchKind): number {
  const v = Math.min(1, Math.max(0, x));
  switch (kind) {
    case 'linear': return v;
    case 'sqrt': return Math.sqrt(v);
    case 'log': return Math.log10(1 + 999 * v) / 3;
    default: return Math.asinh(10 * v) / Math.asinh(10);
  }
}

const STOPS: Record<string, [number, number, number][]> = {
  inferno: [[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164]],
  viridis: [[68, 1, 84], [70, 50, 127], [54, 92, 141], [39, 127, 142], [31, 161, 135], [74, 194, 109], [159, 218, 58], [253, 231, 37]],
  diverging: [[33, 102, 172], [103, 169, 207], [209, 229, 240], [247, 247, 247], [253, 219, 199], [239, 138, 98], [178, 24, 43]],
};

export function buildLut(kind: ColorMapKind | 'diverging'): Uint8ClampedArray {
  const lut = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    let r: number, g: number, b: number;
    if (kind === 'gray') { r = g = b = i; }
    else if (kind === 'invert') { r = g = b = 255 - i; }
    else {
      const stops = STOPS[kind];
      const pos = t * (stops.length - 1);
      const lo = Math.floor(pos), hi = Math.min(stops.length - 1, lo + 1), f = pos - lo;
      r = stops[lo][0] + (stops[hi][0] - stops[lo][0]) * f;
      g = stops[lo][1] + (stops[hi][1] - stops[lo][1]) * f;
      b = stops[lo][2] + (stops[hi][2] - stops[lo][2]) * f;
    }
    lut[i * 3] = r; lut[i * 3 + 1] = g; lut[i * 3 + 2] = b;
  }
  return lut;
}

/** Pixel (x right, y up, 0-based) -> RA/Dec on the north-up TAN grid. */
export function pixelToWorld(x: number, y: number, grid: BlinkResult['grid']): [number, number] {
  const d2r = Math.PI / 180;
  const scale = grid.pixscale_arcsec / 3600;
  const xi = -(x - grid.crpix[0]) * scale * d2r;
  const eta = (y - grid.crpix[1]) * scale * d2r;
  const dec0 = grid.dec * d2r;
  const den = Math.cos(dec0) - eta * Math.sin(dec0);
  const ra = grid.ra + Math.atan2(xi, den) / d2r;
  const dec = Math.atan2(Math.sin(dec0) + eta * Math.cos(dec0), Math.sqrt(xi * xi + den * den)) / d2r;
  return [((ra % 360) + 360) % 360, dec];
}

/** RA/Dec -> pixel (x right, y up, 0-based) on the north-up TAN grid. Null if behind the tangent plane. */
export function worldToPixel(ra: number, dec: number, grid: BlinkResult['grid']): [number, number] | null {
  const d2r = Math.PI / 180;
  const a = ra * d2r, d = dec * d2r, a0 = grid.ra * d2r, d0 = grid.dec * d2r;
  const cosc = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(a - a0);
  if (cosc <= 0) return null;
  const xi = (Math.cos(d) * Math.sin(a - a0)) / cosc / d2r;
  const eta = (Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(a - a0)) / cosc / d2r;
  const scale = grid.pixscale_arcsec / 3600;
  return [grid.crpix[0] - xi / scale, grid.crpix[1] + eta / scale];
}

export function mjdToYear(mjd: number): number {
  return 2000 + (mjd - 51544.5) / 365.25;
}

/** Linear proper-motion propagation (pm in mas/yr, pmra includes cos dec). */
export function propagate(ra: number, dec: number, pmra: number, pmdec: number, fromYear: number, toYear: number): [number, number] {
  const dt = toYear - fromYear;
  const cosd = Math.max(Math.cos((dec * Math.PI) / 180), 1e-6);
  return [ra + (pmra * dt) / 3.6e6 / cosd, dec + (pmdec * dt) / 3.6e6];
}

export interface CatalogSource {
  id: string; ra: number; dec: number; pmra: number; pmdec: number; mag: number | null; parallax?: number | null;
}

export interface CatalogOverlay {
  catalog: 'gaia' | 'catwise'; label: string; band: string; ref_epoch: number; count: number; truncated: boolean;
  sources: CatalogSource[];
}

export interface PhotPoint {
  mjd: number; date: string; detector: number; obs_id: string; wavelength_um: number | null;
  flux_mjy: number | null; err_mjy: number | null; saturated: boolean; masked_fraction: number; flagged: boolean;
}

export interface PhotometryResult {
  position: { ra: number; dec: number; name?: string | null };
  aperture_arcsec: number; n_points: number; n_good: number; points: PhotPoint[]; units: string; elapsed_s: number;
}

// ---------------------------------------------------------------- moving-object search
export type SearchKind = 'asteroids' | 'proper_motion';
export type ReviewStatus = 'unreviewed' | 'real' | 'artifact' | 'unsure';

export interface CandidateDetection {
  frame: number; mjd: number; date: string; x: number; y: number; ra: number; dec: number;
  z: number; flux: number; detectors: number[]; on_star: boolean;
}

export interface TargetCheck {
  significance: number; err_mas_per_year: number | null; baseline_years: number; detected: boolean;
  expected_pm_mas_per_year?: number; measured_pm_mas_per_year?: number; expected_pa_deg?: number; measured_pa_deg?: number;
  difference_mas_per_year?: number; agrees?: boolean; confirmed?: boolean;
}

export interface Candidate {
  id: string; search: SearchKind; class: string; score: number; ra: number; dec: number; x: number; y: number;
  t0_mjd: number; t0_date: string; n_detections: number; n_detectors: number; visits: number; rms_px: number;
  rate_px_per_day: [number, number]; rate_arcsec_per_hour: number; rate_arcsec_per_year: number;
  position_angle_deg: number | null; mean_z: number; recurrence?: number | null; detections: CandidateDetection[];
  metrics?: Record<string, number | string | boolean | string[] | null>; measured_pm_mas_per_year?: [number, number];
  is_target?: boolean; target_name?: string | null; expected_pm_mas_per_year?: [number, number];
  target_check?: TargetCheck;
  match: null | {
    type: 'known_sso' | 'star'; name: string; kind?: string; vmag?: number | null; catalog?: string; mag?: number | null;
    pm_mas_per_year?: number; sep_arcsec: number; predicted_rate_arcsec_per_hour?: number;
  };
  status?: ReviewStatus; note?: string; run_id?: string; created_at?: string;
}

export interface KnownObject {
  name: string; kind: string; vmag: number | null; rate_ra: number; rate_dec: number;
  positions: { frame: number; x: number; y: number; ra: number; dec: number }[];
  in_field: boolean; recovered_by: string | null;
}

export interface DetectionResult {
  run_id: string; search: SearchKind; params: Record<string, unknown>;
  summary: {
    frames: number; searched_frames: number; n_detections: number; n_single_frame: number; n_candidates: number;
    by_class: Record<string, number>; known_in_field: number; known_recovered: number;
    known_bright_in_field: number; known_bright_recovered: number; pass_index: number | null;
    z_thresh: number; notes: string[]; elapsed_s: number;
    noisy_frames?: number; sources_measured?: number | null; astrometric_floor_px?: number | null;
  };
  candidates: Candidate[]; known_objects: KnownObject[]; blink: BlinkResult; is_simulated: boolean;
}

export interface Annotation {
  frame: number | null; // null = every frame
  x: number; y: number; color: string; shape: 'circle' | 'diamond' | 'square';
  size?: number; emphasis?: boolean; label?: string;
}

export interface AnnotationPath { points: [number, number][]; color: string; dashed?: boolean; width?: number }

export const CLASS_COLORS: Record<string, string> = {
  unknown_mover: '#f472b6',
  pm_candidate: '#f472b6',
  target_measurement: '#38bdf8',
  known_sso: '#22d3ee',
  known_pm_star: '#facc15',
  moving_object: '#22d3ee',
  pm_unconfirmed: '#fbbf24',
  variable: '#a78bfa',
  stationary_transient: '#c084fc',
  variable_or_residual: '#94a3b8',
  low_confidence: '#64748b',
};

export const OVERLAY_COLORS: Record<string, string> = { gaia: '#facc15', catwise: '#4ade80' };
export const DETECTOR_COLORS = ['#a78bfa', '#60a5fa', '#22d3ee', '#4ade80', '#facc15', '#f87171'];

export function formatRA(deg: number): string {
  const h = deg / 15;
  const hh = Math.floor(h);
  const m = (h - hh) * 60;
  const mm = Math.floor(m);
  const ss = (m - mm) * 60;
  return `${String(hh).padStart(2, '0')}h${String(mm).padStart(2, '0')}m${ss.toFixed(2).padStart(5, '0')}s`;
}

export function formatDec(deg: number): string {
  const sign = deg < 0 ? '-' : '+';
  const a = Math.abs(deg);
  const dd = Math.floor(a);
  const m = (a - dd) * 60;
  const mm = Math.floor(m);
  const ss = (m - mm) * 60;
  return `${sign}${String(dd).padStart(2, '0')}°${String(mm).padStart(2, '0')}′${ss.toFixed(1).padStart(4, '0')}″`;
}

export function queryFromParams(p: URLSearchParams): BlinkQuery | null {
  const target = p.get('target') || undefined;
  const ra = p.get('ra') !== null ? Number(p.get('ra')) : undefined;
  const dec = p.get('dec') !== null ? Number(p.get('dec')) : undefined;
  const hasCoords = ra !== undefined && dec !== undefined && Number.isFinite(ra) && Number.isFinite(dec);
  if (!target && !hasCoords) return null;
  const num = (k: string, d: number, lo: number, hi: number) => {
    const v = Number(p.get(k));
    return p.get(k) !== null && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : d;
  };
  const det = p.get('det') || DEFAULT_QUERY.detector;
  return {
    target,
    ra: hasCoords ? ra : undefined,
    dec: hasCoords ? dec : undefined,
    fov: num('fov', DEFAULT_QUERY.fov, 0.02, 0.5),
    detector: /^(all|[1-6](,[1-6])*)$/.test(det) ? det : DEFAULT_QUERY.detector,
    mode: p.get('mode') === 'frames' ? 'frames' : p.get('mode') === 'pass' ? 'pass' : 'epoch',
    pass_index: p.get('pass') !== null && Number.isInteger(Number(p.get('pass'))) ? Math.max(0, Number(p.get('pass'))) : undefined,
    per_epoch: Math.round(num('per', DEFAULT_QUERY.per_epoch, 1, 12)),
    max_frames: Math.round(num('max', DEFAULT_QUERY.max_frames, 2, 48)),
    band: parseBand(p.get('band') ?? undefined) ? (p.get('band') as string) : undefined,
  };
}

export function queryToParams(q: BlinkQuery): Record<string, string> {
  const out: Record<string, string> = {};
  if (q.target) out.target = q.target;
  if (q.ra !== undefined && q.dec !== undefined) { out.ra = q.ra.toFixed(6); out.dec = q.dec.toFixed(6); }
  out.fov = String(q.fov);
  out.det = q.detector;
  out.mode = q.mode;
  if (q.mode === 'epoch') out.per = String(q.per_epoch);
  else out.max = String(q.max_frames);
  if (q.mode === 'pass' && q.pass_index !== undefined) out.pass = String(q.pass_index);
  if (parseBand(q.band)) out.band = q.band as string;
  return out;
}

/** Human-readable message from an axios error (FastAPI `detail` first). */
interface HttpErrorLike {
  name?: string;
  message?: string;
  code?: string;
  response?: { status?: number; data?: { detail?: unknown } };
}

export function errorText(err: unknown, timeoutMessage: string, networkMessage?: string): string {
  const e = (err ?? {}) as HttpErrorLike;
  if (e.name === 'JobError') return e.message ?? timeoutMessage; // already a server-side, localized message
  const d = e.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d) && d[0] && typeof d[0] === 'object' && 'msg' in d[0]) return String((d[0] as { msg: unknown }).msg);
  if (e.code === 'ECONNABORTED') return timeoutMessage;
  if (!e.response && networkMessage) return networkMessage; // backend down or CORS-blocked
  if (e.response?.status === 404) return networkMessage ?? e.message ?? timeoutMessage;
  return e.message || timeoutMessage;
}

export function apiParams(q: BlinkQuery): Record<string, string | number> {
  const out: Record<string, string | number> = {
    fov: q.fov, detector: q.detector, mode: q.mode, per_epoch: q.per_epoch, max_frames: q.max_frames,
  };
  if (q.mode === 'pass' && q.pass_index !== undefined) out.pass_index = q.pass_index;
  if (q.ra !== undefined && q.dec !== undefined) { out.ra = q.ra; out.dec = q.dec; }
  if (q.target) out.target = q.target;
  const band = parseBand(q.band);
  if (band) { out.wl_min = band[0]; out.wl_max = band[1]; }
  return out;
}
