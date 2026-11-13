import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { GitCompare, Search, AlertTriangle, Sparkles } from 'lucide-react';
import JobProgressBar from '../components/common/JobProgressBar';
import api from '../services/api';
import {
  BlinkResult, DETECTOR_INFO, DecodedFrame, buildLut, decodeFrames, errorText, percentiles, stretchValue,
} from '../lib/spherex';
import { JobProgress, isAbort, runJob } from '../lib/jobs';

type Mode = 'side' | 'difference' | 'blink' | 'overlay';
const card = 'rounded-2xl border border-white/[0.08] bg-[#0a1020]/80 p-4';
const input = 'w-full px-3 py-2 rounded-lg bg-[#0b1224] border border-white/10 text-sm text-white';
const PRESETS = [
  { name: "Barnard's Star", det: '3' }, { name: 'RW Aurigae', det: '3' }, { name: 'R Draconis', det: '3' },
  { name: 'Epsilon Indi B', det: '4' }, { name: 'WISE 0855-0714', det: '6' },
];

/** Paint one frame (or the A-B difference) into a canvas, north up, with a shared stretch. */
function FrameCanvas({ a, b, w, h, lo, hi, diffLim, mode, label }: {
  a: DecodedFrame; b?: DecodedFrame; w: number; h: number; lo: number; hi: number; diffLim: number; mode: 'plain' | 'difference'; label: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const gray = useMemo(() => buildLut('gray'), []);
  const div = useMemo(() => buildLut('diverging'), []);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    const img = ctx.createImageData(w, h);
    for (let r = 0; r < h; r++) {
      const y = h - 1 - r;
      for (let x = 0; x < w; x++) {
        const i = y * w + x, p = (r * w + x) * 4;
        let k = -1;
        if (mode === 'difference' && b) {
          const d = a.values[i] - b.values[i];
          if (Number.isFinite(d)) k = Math.round(Math.min(1, Math.max(0, (d / diffLim + 1) / 2)) * 255) * 3;
        } else {
          const v = a.values[i];
          if (Number.isFinite(v)) k = Math.round(stretchValue((v - lo) / Math.max(hi - lo, 1e-12), 'asinh') * 255) * 3;
        }
        const lut = mode === 'difference' ? div : gray;
        if (k < 0) { img.data[p] = 22; img.data[p + 1] = 26; img.data[p + 2] = 38; }
        else { img.data[p] = lut[k]; img.data[p + 1] = lut[k + 1]; img.data[p + 2] = lut[k + 2]; }
        img.data[p + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [a, b, w, h, lo, hi, diffLim, mode, gray, div]);
  return (
    <div className="relative aspect-square w-full rounded-xl overflow-hidden border border-white/10 bg-black">
      <canvas ref={ref} className="absolute inset-0 w-full h-full" style={{ imageRendering: 'pixelated' }} />
      <div className="absolute top-2 left-2 px-2 py-0.5 rounded bg-black/70 text-[11px] font-mono text-white">{label}</div>
      <div className="absolute top-2 right-2 px-1.5 py-0.5 rounded bg-black/60 text-[10px] font-mono text-gray-200">N↑ E←</div>
    </div>
  );
}

/** Compare two real SPHEREx survey passes of the same field. */
export default function ComparisonPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [target, setTarget] = useState(params.get('target') ?? "Barnard's Star");
  const [det, setDet] = useState(params.get('det') ?? '3');
  const [fov, setFov] = useState(Number(params.get('fov') ?? 0.1));
  const [result, setResult] = useState<BlinkResult | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ia, setIa] = useState(0);
  const [ib, setIb] = useState(1);
  const [mode, setMode] = useState<Mode>('side');
  const [opacity, setOpacity] = useState(0.5);
  const [tick, setTick] = useState(0);
  const ctrlRef = useRef<AbortController | null>(null);

  const q = params.get('target');
  useEffect(() => {
    if (!q) return;
    const d = params.get('det') ?? '3';
    const f = Number(params.get('fov') ?? 0.1);
    setTarget(q); setDet(d); setFov(f);
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    setLoading(true); setError(null); setResult(null); setProgress(null);
    runJob<BlinkResult>('blink', { target: q, detector: d, fov: f, mode: 'epoch', per_epoch: 6 }, setProgress, ctrl.signal)
      .then((r) => { setResult(r); setIa(0); setIb(Math.max(0, r.frames.length - 1)); })
      .catch((e) => { if (!isAbort(e) && !ctrl.signal.aborted) setError(errorText(e, t('blink.errors.timeout'), t('blink.errors.network', { url: api.defaults.baseURL }))); })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.toString()]);

  useEffect(() => {
    if (mode !== 'blink') return;
    const iv = window.setInterval(() => setTick((x) => x + 1), 700);
    return () => window.clearInterval(iv);
  }, [mode]);

  const frames = useMemo(() => (result ? decodeFrames(result) : []), [result]);
  const [lo, hi] = useMemo(() => (frames.length ? percentiles(frames.map((f) => f.values), [1, 99.7]) : [0, 1]), [frames]);
  const A = frames[ia], B = frames[ib];
  const diffLim = useMemo(() => {
    if (!A || !B) return 1;
    const d = new Float32Array(A.values.length);
    for (let i = 0; i < d.length; i++) d[i] = A.values[i] - B.values[i];
    return Math.max(percentiles([d], [99.5], true)[0], 1e-6);
  }, [A, B]);

  const submit = (name = target, d = det) => setParams({ target: name, det: d, fov: String(fov) });
  const w = result?.grid.width ?? 0, h = result?.grid.height ?? 0;
  const lab = (f: DecodedFrame | undefined, k: string) => (f ? `${k}: ${f.meta.date_start.slice(0, 10)} → ${f.meta.date_end.slice(0, 10)}` : k);
  const days = A && B ? Math.round(Math.abs(B.meta.mjd - A.meta.mjd)) : 0;

  return (
    <div className="space-y-4 p-4 md:p-6 max-w-6xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2"><GitCompare className="w-6 h-6 text-blue-400" />{t('comparison.title')}</h1>
        <p className="text-sm text-gray-500 mt-1">{t('cmp.subtitle')}</p>
      </div>

      <form onSubmit={(e) => { e.preventDefault(); submit(); }} className={`${card} space-y-3`}>
        <div className="grid grid-cols-1 md:grid-cols-[1fr_200px_140px_auto] gap-2 items-end">
          <label className="text-[11px] text-gray-400">{t('blink.search.label')}
            <div className="relative"><Search className="w-4 h-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input className={`${input} pl-9`} value={target} onChange={(e) => setTarget(e.target.value)} /></div>
          </label>
          <label className="text-[11px] text-gray-400">{t('blink.search.detector')}
            <select className={input} value={det} onChange={(e) => setDet(e.target.value)}>
              {['1', '2', '3', '4', '5', '6', 'all'].map((d) => <option key={d} value={d}>{d === 'all' ? t('blink.search.allDetectors') : `D${d}`} · {DETECTOR_INFO[d]}</option>)}
            </select>
          </label>
          <label className="text-[11px] text-gray-400">{t('blink.search.fov')}
            <select className={input} value={fov} onChange={(e) => setFov(Number(e.target.value))}>
              {[0.05, 0.1, 0.2, 0.3].map((v) => <option key={v} value={v}>{v}°</option>)}
            </select>
          </label>
          <button type="submit" disabled={loading} className="px-5 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-sm font-semibold text-[#04101f]">{t('blink.search.button')}</button>
        </div>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button type="button" key={p.name} onClick={() => { setTarget(p.name); setDet(p.det); submit(p.name, p.det); }}
              className="px-2.5 py-1 rounded-full text-[11px] border border-sky-500/30 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20">{p.name}</button>
          ))}
        </div>
      </form>

      {loading && <div className={card}><JobProgressBar progress={progress} hint={t('blink.loadingHint')} onCancel={() => { ctrlRef.current?.abort(); setLoading(false); }} /></div>}
      {!loading && error && <div className={`${card} border-red-500/30 text-sm text-red-200 flex gap-2`}><AlertTriangle className="w-4 h-4 shrink-0" />{error}</div>}
      {!loading && !error && !result && <div className={`${card} text-sm text-gray-400`}>{t('cmp.intro')}</div>}

      {!loading && result && A && B && (
        <div className={`${card} space-y-3`}>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-[11px] text-gray-400">{t('cmp.epochA')}
              <select className={input} value={ia} onChange={(e) => setIa(Number(e.target.value))}>
                {frames.map((f, i) => <option key={i} value={i}>{i + 1}. {f.meta.date_start.slice(0, 10)} ({f.meta.n_frames})</option>)}
              </select>
            </label>
            <label className="text-[11px] text-gray-400">{t('cmp.epochB')}
              <select className={input} value={ib} onChange={(e) => setIb(Number(e.target.value))}>
                {frames.map((f, i) => <option key={i} value={i}>{i + 1}. {f.meta.date_start.slice(0, 10)} ({f.meta.n_frames})</option>)}
              </select>
            </label>
            <div className="flex rounded-lg overflow-hidden border border-white/10">
              {(['side', 'difference', 'blink', 'overlay'] as Mode[]).map((m) => (
                <button key={m} type="button" onClick={() => setMode(m)}
                  className={`px-3 py-2 text-xs ${mode === m ? 'bg-sky-500/20 text-sky-300' : 'bg-white/[0.03] text-gray-400 hover:text-gray-200'}`}>{t(`cmp.mode.${m}`)}</button>
              ))}
            </div>
            {mode === 'overlay' && (
              <label className="text-[11px] text-gray-400 flex flex-col">{t('comparison.controls.opacity')}: {Math.round(opacity * 100)}%
                <input type="range" min={0} max={1} step={0.01} value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} className="accent-sky-400 w-40" />
              </label>
            )}
            <span className="text-[11px] text-gray-500">{t('cmp.baseline', { days })}</span>
          </div>

          {mode === 'side' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <FrameCanvas a={A} w={w} h={h} lo={lo} hi={hi} diffLim={diffLim} mode="plain" label={lab(A, 'A')} />
              <FrameCanvas a={B} w={w} h={h} lo={lo} hi={hi} diffLim={diffLim} mode="plain" label={lab(B, 'B')} />
            </div>
          )}
          {mode === 'difference' && (
            <div className="max-w-xl mx-auto">
              <FrameCanvas a={B} b={A} w={w} h={h} lo={lo} hi={hi} diffLim={diffLim} mode="difference" label={`B − A (${days} d)`} />
              <p className="text-[11px] text-gray-500 mt-2">{t('cmp.diffHelp')}</p>
            </div>
          )}
          {mode === 'blink' && (
            <div className="max-w-xl mx-auto">
              <FrameCanvas a={tick % 2 ? B : A} w={w} h={h} lo={lo} hi={hi} diffLim={diffLim} mode="plain" label={lab(tick % 2 ? B : A, tick % 2 ? 'B' : 'A')} />
            </div>
          )}
          {mode === 'overlay' && (
            <div className="relative max-w-xl mx-auto">
              <FrameCanvas a={A} w={w} h={h} lo={lo} hi={hi} diffLim={diffLim} mode="plain" label={lab(A, 'A')} />
              <div className="absolute inset-0" style={{ opacity }}>
                <FrameCanvas a={B} w={w} h={h} lo={lo} hi={hi} diffLim={diffLim} mode="plain" label={lab(B, 'B')} />
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 text-[11px] text-gray-400">
            {[A, B].map((f, i) => (
              <div key={i} className="rounded-lg bg-white/[0.02] border border-white/5 p-2">
                <div className="text-gray-300 font-semibold">{i ? 'B' : 'A'}</div>
                <div>{t('blink.panels.exposures')}: {f.meta.n_frames} · {t('blink.panels.wavelength')}: {f.meta.wavelength_um ? `${f.meta.wavelength_um[0]}–${f.meta.wavelength_um[1]} µm` : '—'}</div>
                <div>{t('blink.panels.masked')}: {(f.meta.masked_fraction * 100).toFixed(1)}%</div>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between text-[10px] text-gray-600">
            <span>{result.source}</span>
            <Link className="text-sky-400 hover:underline flex items-center gap-1" to={`/?target=${encodeURIComponent(target)}&fov=${fov}&det=${det}&mode=epoch&per=6`}><Sparkles className="w-3 h-3" />Blink</Link>
          </div>
        </div>
      )}
    </div>
  );
}
