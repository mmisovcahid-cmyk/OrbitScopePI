import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Radar, Search, AlertTriangle, CheckCircle2, XCircle, HelpCircle, Download, ExternalLink, Eye, EyeOff, Clock,
} from 'lucide-react';
import BlinkViewer from '../components/blink/BlinkViewer';
import JobProgressBar from '../components/common/JobProgressBar';
import { JobProgress, isAbort, runJob } from '../lib/jobs';
import { spherexService } from '../services';
import api from '../services/api';
import {
  Annotation, AnnotationPath, CLASS_COLORS, Candidate, DetectionResult, ReviewStatus, SearchKind, TargetCheck, errorText,
  formatDec, formatRA,
} from '../lib/spherex';

const card = 'rounded-2xl border border-white/[0.08] bg-[#0a1020]/80 p-4';
const input = 'w-full px-3 py-2 rounded-lg bg-[#0b1224] border border-white/10 text-sm text-white placeholder:text-gray-600 focus:outline-none focus:border-sky-500/60';
const SSO_COLOR = '#22d3ee';
// Verified examples: Notburga (V=13.5) is recovered in pass 1; eps Indi B and WISE 0855 are
// recovered as known proper-motion objects with the right speed and direction.
const PRESETS = [
  { label: '626 Notburga field (asteroid)', target: '9.6915 4.0152', search: 'asteroids' as SearchKind, det: '1,4', fov: 0.3 },
  { label: 'Ecliptic field 00h40m +04°', target: '10.0 4.0', search: 'asteroids' as SearchKind, det: '1,4', fov: 0.3 },
  { label: 'WISE 0855-0714 (PM)', target: 'WISE 0855-0714', search: 'proper_motion' as SearchKind, det: '6', fov: 0.1 },
  { label: 'Epsilon Indi B (PM)', target: 'Epsilon Indi B', search: 'proper_motion' as SearchKind, det: '4', fov: 0.1 },
];

interface Form {
  target: string; search: SearchKind; fov: number; det: string; pass: string; max: number; z: number;
}

const DEFAULT_FORM: Form = { target: '', search: 'asteroids', fov: 0.2, det: '1,4', pass: 'auto', max: 36, z: 5 };

function formFromParams(p: URLSearchParams): Form | null {
  const target = p.get('target');
  if (!target) return null;
  const search: SearchKind = p.get('search') === 'proper_motion' ? 'proper_motion' : 'asteroids';
  const num = (k: string, d: number) => (p.get(k) !== null && Number.isFinite(Number(p.get(k))) ? Number(p.get(k)) : d);
  return {
    target, search,
    fov: num('fov', 0.2),
    det: p.get('det') || (search === 'asteroids' ? '1,4' : '3'),
    pass: p.get('pass') ?? 'auto',
    max: num('max', 36),
    z: num('z', 5),
  };
}

function formToParams(f: Form): Record<string, string> {
  const o: Record<string, string> = { target: f.target, search: f.search, fov: String(f.fov), det: f.det, max: String(f.max), z: String(f.z) };
  if (f.search === 'asteroids' && f.pass !== 'auto') o.pass = f.pass;
  return o;
}

function apiFromForm(f: Form): Record<string, string | number> {
  const o: Record<string, string | number> = {
    target: f.target, search: f.search, fov: f.fov, detector: f.det, max_frames: f.max, z_thresh: f.z,
  };
  if (f.search === 'asteroids' && f.pass !== 'auto') o.pass_index = Number(f.pass);
  return o;
}

export default function DetectionPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const urlForm = useMemo(() => formFromParams(params), [params]);
  const [form, setForm] = useState<Form>(() => urlForm ?? DEFAULT_FORM);
  const [result, setResult] = useState<DetectionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const ctrlRef = useRef<AbortController | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [jump, setJump] = useState<{ frame: number; nonce: number } | null>(null);
  const [showKnown, setShowKnown] = useState(true);
  const [showWeak, setShowWeak] = useState(false);
  const [reviews, setReviews] = useState<Record<string, ReviewStatus>>({});
  const [saved, setSaved] = useState<Candidate[]>([]);
  const [savedFilter, setSavedFilter] = useState<string>('');
  const [savedCounts, setSavedCounts] = useState<Record<string, number>>({});

  const loadSaved = useCallback(() => {
    spherexService.candidates(savedFilter).then((res) => {
      setSaved(res.data?.data?.candidates ?? []);
      setSavedCounts(res.data?.data?.counts ?? {});
    }).catch(() => undefined);
  }, [savedFilter]);
  useEffect(() => { loadSaved(); }, [loadSaved]);

  useEffect(() => {
    if (!urlForm) return;
    setForm(urlForm);
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    setLoading(true); setError(null); setProgress(null); setSelected(null);
    runJob<DetectionResult>('detect', apiFromForm(urlForm), setProgress, ctrl.signal)
      .then((res) => { setResult(res); setReviews({}); loadSaved(); })
      .catch((e) => {
        if (isAbort(e) || ctrl.signal.aborted) return;
        setResult(null);
        setError(errorText(e, t('blink.errors.timeout'), t('blink.errors.network', { url: api.defaults.baseURL })));
      })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => { ctrl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.toString()]);

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!form.target.trim()) { setError(t('blink.errors.empty')); return; }
    setParams(formToParams({ ...form, target: form.target.trim() }));
  };

  const setSearch = (s: SearchKind) =>
    setForm((f) => ({ ...f, search: s, det: s === 'asteroids' ? '1,4' : '3', fov: s === 'asteroids' ? 0.2 : 0.1 }));

  const review = async (c: Candidate, status: ReviewStatus) => {
    try {
      await spherexService.review(c.id, status);
      setReviews((r) => ({ ...r, [c.id]: status }));
      loadSaved();
    } catch (e) {
      setError(errorText(e, t('blink.errors.timeout')));
    }
  };

  const visible = useMemo(() => (result?.candidates ?? []).filter((c) =>
    showWeak || !['low_confidence', 'variable_or_residual', 'stationary_transient'].includes(c.class)), [result, showWeak]);

  const annotations = useMemo<Annotation[]>(() => {
    if (!result) return [];
    const out: Annotation[] = [];
    for (const c of visible) {
      const color = CLASS_COLORS[c.class] ?? '#e5e7eb';
      for (const d of c.detections) {
        out.push({ frame: d.frame, x: d.x, y: d.y, color, shape: 'circle', emphasis: c.id === selected,
          label: c.id === selected ? c.id : undefined });
      }
    }
    if (showKnown) {
      for (const k of result.known_objects) {
        for (const p of k.positions) {
          out.push({ frame: p.frame, x: p.x, y: p.y, color: SSO_COLOR, shape: 'diamond', size: 0.8,
            label: (k.vmag ?? 99) <= 19 ? k.name.split(' (')[0] : undefined });
        }
      }
    }
    return out;
  }, [result, visible, selected, showKnown]);

  const paths = useMemo<AnnotationPath[]>(() => {
    if (!result) return [];
    const out: AnnotationPath[] = visible.filter((c) => c.detections.length > 1).map((c) => ({
      points: c.detections.map((d) => [d.x, d.y] as [number, number]),
      color: CLASS_COLORS[c.class] ?? '#e5e7eb', width: c.id === selected ? undefined : 0.25,
    }));
    if (showKnown) {
      for (const k of result.known_objects) {
        if (k.positions.length > 1) out.push({ points: k.positions.map((p) => [p.x, p.y] as [number, number]), color: SSO_COLOR, dashed: true, width: 0.2 });
      }
    }
    return out;
  }, [result, visible, selected, showKnown]);

  const select = (c: Candidate) => {
    setSelected(c.id);
    setJump({ frame: c.detections[0].frame, nonce: Date.now() });
  };

  const sel = result?.candidates.find((c) => c.id === selected) ?? null;
  const s = result?.summary;
  const passes = result?.blink.coverage.n_epochs ?? 4;

  const classLabel = (k: string) => t(`detect.classes.${k}`, { defaultValue: k });
  const statusOf = (c: Candidate): ReviewStatus => reviews[c.id] ?? (c.status as ReviewStatus) ?? 'unreviewed';

  const ReviewButtons = ({ c }: { c: Candidate }) => {
    const st = statusOf(c);
    const b = (status: ReviewStatus, Icon: typeof CheckCircle2, color: string, title: string) => (
      <button onClick={(e) => { e.stopPropagation(); review(c, status); }} title={title}
        className={`p-1 rounded-md border ${st === status ? `${color} bg-white/10 border-white/20` : 'text-gray-500 border-transparent hover:text-gray-200'}`}>
        <Icon className="w-4 h-4" />
      </button>
    );
    return (
      <div className="flex gap-1">
        {b('real', CheckCircle2, 'text-emerald-400', t('detect.review.real'))}
        {b('artifact', XCircle, 'text-red-400', t('detect.review.artifact'))}
        {b('unsure', HelpCircle, 'text-amber-300', t('detect.review.unsure'))}
      </div>
    );
  };

  const blinkLink = (c: Candidate) => {
    const q = new URLSearchParams({
      ra: c.ra.toFixed(6), dec: c.dec.toFixed(6), fov: '0.1', det: String(result?.params.detectors ? (result.params.detectors as number[]).join(',') : 'all'),
      mode: c.search === 'asteroids' ? 'pass' : 'epoch',
      ...(c.search === 'asteroids' && result?.summary.pass_index != null ? { pass: String(result.summary.pass_index) } : {}),
      ...(c.search === 'asteroids' ? { max: String(result?.params.max_frames ?? 36) } : { per: '4' }),
    });
    return `/?${q}`;
  };

  const rateText = (c: Candidate) =>
    c.search === 'asteroids' ? `${c.rate_arcsec_per_hour.toFixed(1)}″/h` : `${c.rate_arcsec_per_year.toFixed(1)}″/yr`;

  return (
    <div className="p-4 md:p-6 space-y-4 max-w-[1500px] mx-auto">
      <div>
        <h1 className="text-xl md:text-2xl font-bold text-white flex items-center gap-2">
          <Radar className="w-6 h-6 text-sky-400" /> {t('detect.title')}
        </h1>
        <p className="text-sm text-gray-400 mt-1 max-w-4xl">{t('detect.subtitle')}</p>
      </div>

      {/* Form */}
      <form onSubmit={submit} className={`${card} space-y-3`}>
        <div className="flex flex-wrap gap-2">
          {(['asteroids', 'proper_motion'] as SearchKind[]).map((k) => (
            <button type="button" key={k} onClick={() => setSearch(k)}
              className={`px-3 py-1.5 rounded-lg text-xs border ${form.search === k ? 'border-sky-500/60 bg-sky-500/15 text-sky-200' : 'border-white/10 text-gray-400 hover:text-gray-200'}`}>
              {t(`detect.search.${k}`)}
            </button>
          ))}
          <span className="text-[11px] text-gray-500 self-center">{t(`detect.searchHelp.${form.search}`)}</span>
        </div>
        <div className="flex flex-col md:flex-row gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input className={`${input} pl-9`} value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })}
              placeholder={t('blink.search.placeholder')} aria-label={t('blink.search.label')} />
          </div>
          <button type="submit" disabled={loading}
            className="px-5 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-sm font-semibold text-[#04101f]">
            {t('detect.run')}
          </button>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          <label className="text-[11px] text-gray-400 flex flex-col gap-1">{t('blink.search.fov')}
            <select className={input} value={form.fov} onChange={(e) => setForm({ ...form, fov: Number(e.target.value) })}>
              {[0.05, 0.1, 0.2, 0.3, 0.5].map((v) => <option key={v} value={v}>{v}° ({Math.round(v * 60)}′)</option>)}
            </select>
          </label>
          <label className="text-[11px] text-gray-400 flex flex-col gap-1">{t('blink.search.detector')}
            <select className={input} value={form.det} onChange={(e) => setForm({ ...form, det: e.target.value })}>
              {['1,4', '2,5', '3,6', '1', '2', '3', '4', '5', '6', 'all'].map((d) => (
                <option key={d} value={d}>{d === 'all' ? t('blink.search.allDetectors') : `D${d.replace(',', '+D')}`}</option>
              ))}
            </select>
          </label>
          {form.search === 'asteroids' && (
            <label className="text-[11px] text-gray-400 flex flex-col gap-1">{t('detect.pass')}
              <select className={input} value={form.pass} onChange={(e) => setForm({ ...form, pass: e.target.value })}>
                <option value="auto">{t('detect.passAuto')}</option>
                {Array.from({ length: Math.max(passes, 3) }, (_, i) => <option key={i} value={String(i)}>{t('blink.panels.epoch')} {i + 1}</option>)}
              </select>
            </label>
          )}
          <label className="text-[11px] text-gray-400 flex flex-col gap-1">{t('detect.maxFrames')}
            <select className={input} value={form.max} onChange={(e) => setForm({ ...form, max: Number(e.target.value) })}>
              {[12, 24, 36, 48].map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </label>
          <label className="text-[11px] text-gray-400 flex flex-col gap-1">{t('detect.threshold')}
            <select className={input} value={form.z} onChange={(e) => setForm({ ...form, z: Number(e.target.value) })}>
              {[4, 5, 6, 8].map((v) => <option key={v} value={v}>{v} σ</option>)}
            </select>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] text-gray-500">{t('blink.search.tryTargets')}</span>
          {PRESETS.map((p) => (
            <button type="button" key={p.label}
              onClick={() => setParams(formToParams({ ...DEFAULT_FORM, target: p.target, search: p.search,
                det: p.det, fov: p.fov, pass: p.search === 'asteroids' ? '0' : 'auto' }))}
              className="px-2.5 py-1 rounded-full text-[11px] border border-sky-500/30 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20">
              {p.label}
            </button>
          ))}
        </div>
      </form>

      {loading && (
        <div className={card}>
          <JobProgressBar
            progress={progress} hint={t('detect.loadingHint')}
            onCancel={() => { ctrlRef.current?.abort(); setLoading(false); setError(t('jobs.cancelled')); }}
          />
        </div>
      )}
      {!loading && error && (
        <div className={`${card} border-red-500/30 flex items-start gap-3`}>
          <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
          <div className="text-sm text-red-200">{error}</div>
        </div>
      )}
      {!loading && !error && !result && (
        <div className={`${card} text-sm text-gray-400 space-y-2`}>
          <h2 className="text-white font-semibold">{t('detect.howTitle')}</h2>
          <ol className="list-decimal list-inside space-y-1">
            <li>{t('detect.how1')}</li><li>{t('detect.how2')}</li><li>{t('detect.how3')}</li><li>{t('detect.how4')}</li>
          </ol>
          <p className="text-[11px] text-gray-500">{t('detect.disclaimer')}</p>
        </div>
      )}

      {!loading && result && s && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
            {[
              [t('detect.stats.frames'), `${s.searched_frames}/${s.frames}`],
              ...(result.search === 'asteroids'
                ? [[t('detect.stats.detections'), `${s.n_detections}`], [t('detect.stats.single'), `${s.n_single_frame}`]]
                : [[t('detect.stats.measured'), `${s.n_detections}`],
                   [t('detect.stats.astrometry'), s.astrometric_floor_px != null ? `${(s.astrometric_floor_px * 6.15).toFixed(2)}″` : '—']]),
              [t('detect.stats.candidates'), `${s.n_candidates}`],
              ...(result.search === 'asteroids'
                ? [[t('detect.stats.knownRecovered'), `${s.known_recovered}/${s.known_in_field}`],
                   [t('detect.stats.brightRecovered'), `${s.known_bright_recovered}/${s.known_bright_in_field}`]]
                : [[t('detect.stats.pm'), `${(s.by_class.pm_candidate ?? 0) + (s.by_class.known_pm_star ?? 0)}`],
                   [t('detect.stats.variable'), `${s.by_class.variable ?? 0}`]]),
            ].map(([label, value]) => (
              <div key={label} className={card}>
                <div className="text-[11px] text-gray-500">{label}</div>
                <div className="text-lg font-semibold text-white">{value}</div>
              </div>
            ))}
          </div>
          {s.notes.length > 0 && (
            <div className="text-[11px] text-amber-300 space-y-0.5">{s.notes.map((n) => <div key={n}>⚠ {n}</div>)}</div>
          )}

          <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_480px] gap-4">
            <div className={`${card} space-y-2`}>
              <div className="flex flex-wrap items-center gap-3 text-[11px] text-gray-400">
                <span className="font-mono text-gray-500">{result.run_id}</span>
                {result.search === 'asteroids' && (
                  <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={showKnown} onChange={(e) => setShowKnown(e.target.checked)} className="accent-cyan-400" />
                    <span style={{ color: SSO_COLOR }}>◇</span> {t('detect.showKnown')}
                  </label>
                )}
                <label className="flex items-center gap-1.5">
                  <input type="checkbox" checked={showWeak} onChange={(e) => setShowWeak(e.target.checked)} className="accent-sky-400" />
                  {t('detect.showWeak')}
                </label>
                <span>{t('blink.panels.epoch')}: {s.pass_index != null ? s.pass_index + 1 : '—'} · {s.elapsed_s}s</span>
              </div>
              <BlinkViewer result={result.blink} annotations={annotations} paths={paths} jumpTo={jump} autoplay={false} />
            </div>

            <div className="space-y-4">
              {/* Candidates */}
              <div className={card}>
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                  {t('detect.candidates')} ({visible.length})
                </h3>
                {visible.length === 0 ? (
                  <p className="text-xs text-gray-500">{t('detect.none')}</p>
                ) : (
                  <div className="max-h-[420px] overflow-y-auto -mx-2">
                    <table className="w-full text-[11px]">
                      <thead className="text-gray-500 sticky top-0 bg-[#0a1020]">
                        <tr><th className="text-left px-2 py-1">{t('detect.col.class')}</th><th className="text-left">{t('detect.col.match')}</th>
                          <th>{t('detect.col.n')}</th><th>{t('detect.col.rate')}</th><th>S/N</th><th>{t('detect.col.review')}</th></tr>
                      </thead>
                      <tbody>
                        {visible.map((c) => (
                          <tr key={c.id} onClick={() => select(c)}
                            className={`cursor-pointer border-t border-white/5 ${c.id === selected ? 'bg-sky-500/10' : 'hover:bg-white/[0.03]'}`}>
                            <td className="px-2 py-1.5">
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                                style={{ color: CLASS_COLORS[c.class], background: `${CLASS_COLORS[c.class]}1f` }}>
                                {classLabel(c.class)}
                              </span>
                            </td>
                            <td className="text-gray-300 max-w-[140px] truncate" title={c.match?.name}>{c.match?.name ?? '—'}</td>
                            <td className="text-center text-gray-300">{c.n_detections}{c.n_detectors > 1 ? `·${c.n_detectors}D` : ''}</td>
                            <td className="text-center text-gray-300 font-mono">{rateText(c)}</td>
                            <td className="text-center text-gray-300">{c.mean_z}</td>
                            <td className="py-1"><ReviewButtons c={c} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {sel && (
                <div className={card}>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-white font-semibold font-mono">{sel.id}</div>
                      <div className="text-[11px]" style={{ color: CLASS_COLORS[sel.class] }}>{classLabel(sel.class)} · {t('detect.score')} {sel.score}</div>
                    </div>
                    <div className="flex gap-2">
                      <Link to={`/analysis/${sel.id}`} className="px-2 py-1 rounded-lg bg-sky-500/15 border border-sky-500/30 text-[11px] text-sky-200 hover:bg-sky-500/25">
                        {t('analysisLive.open')}
                      </Link>
                      <Link to={blinkLink(sel)} className="px-2 py-1 rounded-lg bg-white/5 border border-white/10 text-[11px] text-gray-200 hover:bg-white/10 flex items-center gap-1">
                        <Eye className="w-3.5 h-3.5" /> Blink
                      </Link>
                      <a href={spherexService.exportUrl(sel.id)} className="px-2 py-1 rounded-lg bg-white/5 border border-white/10 text-[11px] text-gray-200 hover:bg-white/10 flex items-center gap-1">
                        <Download className="w-3.5 h-3.5" /> CSV
                      </a>
                    </div>
                  </div>
                  <p className="text-[11px] text-gray-400 mt-2">{t(`detect.explain.${sel.class}`, { defaultValue: '' })}</p>
                  {sel.target_check && <TargetCheckBox c={sel.target_check} />}
                  {Array.isArray(sel.metrics?.rejected_because) && (sel.metrics.rejected_because as string[]).length > 0 && (
                    <p className="text-[11px] text-amber-300/90 mt-2">
                      {t('detect.rejected')}: {(sel.metrics.rejected_because as string[]).map((r) => t(`detect.reject.${r}`, { defaultValue: r })).join('; ')}.
                    </p>
                  )}
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] mt-2">
                    <dt className="text-gray-500">RA / Dec</dt><dd className="font-mono text-gray-200">{formatRA(sel.ra)} {formatDec(sel.dec)}</dd>
                    <dt className="text-gray-500">{t('detect.col.rate')}</dt><dd className="text-gray-200">{rateText(sel)}{sel.position_angle_deg != null ? ` · PA ${sel.position_angle_deg}°` : ''}</dd>
                    <dt className="text-gray-500">{t('detect.fitRms')}</dt><dd className="text-gray-200">{sel.rms_px} px</dd>
                    {sel.search === 'asteroids' ? (<>
                      <dt className="text-gray-500">{t('detect.visits')}</dt><dd className="text-gray-200">{sel.visits}</dd>
                      {sel.recurrence != null && (<>
                        <dt className="text-gray-500">{t('detect.recurrence')}</dt><dd className="text-gray-200">{sel.recurrence}</dd>
                      </>)}
                    </>) : (<>
                      {sel.measured_pm_mas_per_year && (<>
                        <dt className="text-gray-500">{t('detect.measuredPm')}</dt>
                        <dd className="text-gray-200 font-mono">μα* {(sel.measured_pm_mas_per_year[0] / 1000).toFixed(2)}″ · μδ {(sel.measured_pm_mas_per_year[1] / 1000).toFixed(2)}″ /yr</dd>
                      </>)}
                      {sel.metrics?.pm_sigma != null && (<>
                        <dt className="text-gray-500">{t('detect.significance')}</dt>
                        <dd className="text-gray-200">{String(sel.metrics.pm_sigma)} σ · {String(sel.metrics.shift_px)} px</dd>
                      </>)}
                      {sel.metrics?.flux_ratio != null && (<>
                        <dt className="text-gray-500">{t('detect.fluxRatio')}</dt><dd className="text-gray-200">× {String(sel.metrics.flux_ratio)}</dd>
                      </>)}
                    </>)}
                    {sel.match && (<>
                      <dt className="text-gray-500">{t('detect.col.match')}</dt>
                      <dd className="text-gray-200">{sel.match.name} ({sel.match.sep_arcsec}″{sel.match.vmag != null ? `, V=${sel.match.vmag}` : ''}{sel.match.pm_mas_per_year != null ? `, μ=${(sel.match.pm_mas_per_year / 1000).toFixed(2)}″/yr` : ''})</dd>
                    </>)}
                  </dl>
                  <table className="w-full text-[10px] mt-3 font-mono">
                    <thead className="text-gray-500"><tr><th className="text-left">UTC</th><th>D</th><th className="text-left">RA</th><th className="text-left">Dec</th><th>S/N</th></tr></thead>
                    <tbody>
                      {sel.detections.map((d) => (
                        <tr key={`${d.frame}`} className="text-gray-300 cursor-pointer hover:text-white" onClick={() => setJump({ frame: d.frame, nonce: Date.now() })}>
                          <td>{d.date.slice(0, 19).replace('T', ' ')}</td><td className="text-center">{d.detectors.join('/')}</td>
                          <td>{d.ra.toFixed(5)}</td><td>{d.dec.toFixed(5)}</td><td className="text-center">{d.z}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {result.search === 'asteroids' && (
                <div className={card}>
                  <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    {showKnown ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />} {t('detect.known')} ({result.known_objects.length})
                  </h3>
                  {result.known_objects.length === 0 ? <p className="text-xs text-gray-500">{t('detect.noKnown')}</p> : (
                    <ul className="space-y-1 max-h-48 overflow-y-auto">
                      {result.known_objects.slice().sort((a, b) => (a.vmag ?? 99) - (b.vmag ?? 99)).map((k) => (
                        <li key={k.name} className="text-[11px] flex items-center justify-between gap-2 cursor-pointer hover:text-white text-gray-300"
                          onClick={() => k.positions[0] && setJump({ frame: k.positions[0].frame, nonce: Date.now() })}>
                          <span className="truncate">{k.name}</span>
                          <span className="shrink-0 text-gray-500">V {k.vmag ?? '—'} · {Math.hypot(k.rate_ra, k.rate_dec).toFixed(0)}″/h</span>
                          <span className={`shrink-0 ${k.recovered_by ? 'text-emerald-400' : 'text-gray-600'}`}>{k.recovered_by ? '✓' : '—'}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="text-[10px] text-gray-600 mt-2">{t('detect.knownNote')}</p>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* Saved / reviewed candidates */}
      <div className={card}>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" /> {t('detect.saved')}
          </h3>
          <div className="flex gap-1">
            {['', 'unreviewed', 'real', 'unsure', 'artifact'].map((f) => (
              <button key={f || 'all'} onClick={() => setSavedFilter(f)}
                className={`px-2 py-0.5 rounded-full text-[10px] border ${savedFilter === f ? 'border-sky-500/50 text-sky-200 bg-sky-500/10' : 'border-white/10 text-gray-400'}`}>
                {f ? t(`detect.review.${f}`) : t('detect.all')} {f && savedCounts[f] ? `(${savedCounts[f]})` : ''}
              </button>
            ))}
          </div>
        </div>
        {saved.length === 0 ? <p className="text-xs text-gray-500">{t('detect.noSaved')}</p> : (
          <div className="max-h-72 overflow-y-auto">
            <table className="w-full text-[11px]">
              <tbody>
                {saved.filter((c) => !['low_confidence', 'variable_or_residual', 'stationary_transient'].includes(c.class) || savedFilter).map((c) => (
                  <tr key={c.id} className="border-t border-white/5">
                    <td className="py-1 font-mono"><Link to={`/analysis/${c.id}`} className="text-sky-300 hover:underline">{c.id}</Link></td>
                    <td><span style={{ color: CLASS_COLORS[c.class] }}>{classLabel(c.class)}</span></td>
                    <td className="text-gray-300 truncate max-w-[180px]">{c.match?.name ?? '—'}</td>
                    <td className="font-mono text-gray-400">{formatRA(c.ra)} {formatDec(c.dec)}</td>
                    <td className="text-gray-500">{c.t0_date?.slice(0, 10)}</td>
                    <td><ReviewButtons c={c} /></td>
                    <td>
                      <a href={spherexService.exportUrl(c.id)} className="text-sky-400 hover:text-sky-300 inline-flex items-center gap-0.5">
                        CSV <ExternalLink className="w-3 h-3" />
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/** Measured vs. catalog motion of the requested target (proper-motion search). */
function TargetCheckBox({ c }: { c: TargetCheck }) {
  const { t } = useTranslation();
  const arc = (mas?: number) => (mas == null ? '—' : `${(mas / 1000).toFixed(2)}″/yr`);
  const verdict = c.expected_pm_mas_per_year == null
    ? { text: t('detect.targetCheck.noCatalog'), cls: 'text-gray-400' }
    : c.confirmed
      ? { text: t('detect.targetCheck.confirmed'), cls: 'text-emerald-300' }
      : c.agrees
        ? { text: t('detect.targetCheck.agreesWeak'), cls: 'text-amber-300' }
        : { text: t('detect.targetCheck.disagrees'), cls: 'text-rose-300' };
  return (
    <div className="mt-2 rounded-lg border border-sky-500/20 bg-sky-500/5 p-2 text-[11px]">
      <div className="text-sky-200 font-semibold mb-1">{t('detect.targetCheck.title')}</div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5">
        <dt className="text-gray-500">{t('detect.targetCheck.measured')}</dt>
        <dd className="text-gray-200 font-mono">{arc(c.measured_pm_mas_per_year)}{c.measured_pa_deg != null ? ` · PA ${c.measured_pa_deg}°` : ''}{c.err_mas_per_year != null ? ` ± ${(c.err_mas_per_year / 1000).toFixed(2)}` : ''}</dd>
        <dt className="text-gray-500">{t('detect.targetCheck.expected')}</dt>
        <dd className="text-gray-200 font-mono">{arc(c.expected_pm_mas_per_year)}{c.expected_pa_deg != null ? ` · PA ${c.expected_pa_deg}°` : ''}</dd>
        <dt className="text-gray-500">{t('detect.targetCheck.significance')}</dt>
        <dd className="text-gray-200">{c.significance} σ</dd>
        <dt className="text-gray-500">{t('detect.targetCheck.baseline')}</dt>
        <dd className="text-gray-200">{c.baseline_years} yr</dd>
      </dl>
      <div className={`mt-1 ${verdict.cls}`}>{verdict.text}</div>
    </div>
  );
}
