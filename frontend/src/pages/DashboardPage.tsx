import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Telescope, Activity, HardDrive, Radar, Sparkles, Satellite, AlertTriangle, ExternalLink } from 'lucide-react';
import AllSkyMap, { SkyMarker } from '../components/skymap/AllSkyMap';
import BlinkViewer from '../components/blink/BlinkViewer';
import JobProgressBar from '../components/common/JobProgressBar';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { spherexService } from '../services';
import api from '../services/api';
import { BlinkResult, CLASS_COLORS, Candidate, errorText, formatDec, formatRA } from '../lib/spherex';
import { JobProgress, isAbort, runJob } from '../lib/jobs';

interface Target { id: string; name: string; ra: number; dec: number; kind: string; note: string; detector: number }
interface Run { id: string; created_at: string; params: Record<string, unknown>; summary: Record<string, unknown> }
interface Overview {
  irsa: { reachable: boolean; latency_ms?: number };
  cache: { cutouts: number; size_mb: number; limit_mb: number };
  review_counts: Record<string, number>;
  class_counts: Record<string, number>;
  recent_runs: Run[];
  recent_candidates: Candidate[];
  targets: Target[];
  jobs: Record<string, number>;
}

type Selection =
  | { kind: 'target'; target: Target }
  | { kind: 'candidate'; cand: Candidate }
  | { kind: 'run'; run: Run };

const card = 'rounded-2xl border border-white/[0.08] bg-[#0a1020]/80 p-4';
const HIDDEN = ['low_confidence', 'variable_or_residual', 'stationary_transient'];

/** Sky Explorer: an overview built only from real data (challenge targets, searches and candidates). */
export default function DashboardPage() {
  const { t } = useTranslation();
  const [ov, setOv] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<Selection | null>(null);
  const [preview, setPreview] = useState<BlinkResult | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    spherexService.overview()
      .then((res) => {
        const d: Overview = res.data?.data;
        setOv(d);
        const first = d?.targets?.[0];
        if (first) setSel({ kind: 'target', target: first });
      })
      .catch((e) => setError(errorText(e, t('blink.errors.timeout'), t('blink.errors.network', { url: api.defaults.baseURL }))));
  }, [t]);

  // Real SPHEREx preview for the selected challenge target (cached after the first view).
  useEffect(() => {
    if (sel?.kind !== 'target') { setPreview(null); return; }
    const ctrl = new AbortController();
    setPreview(null); setPreviewError(null); setProgress(null);
    runJob<BlinkResult>('blink', { target: sel.target.name, fov: 0.1, detector: String(sel.target.detector), mode: 'epoch', per_epoch: 4 }, setProgress, ctrl.signal)
      .then(setPreview)
      .catch((e) => { if (!isAbort(e) && !ctrl.signal.aborted) setPreviewError(errorText(e, t('blink.errors.timeout'))); });
    return () => ctrl.abort();
  }, [sel, t]);

  const shownCandidates = useMemo(() => (ov?.recent_candidates ?? []).filter((c) => !HIDDEN.includes(c.class)), [ov]);

  const markers = useMemo<SkyMarker[]>(() => {
    if (!ov) return [];
    const out: SkyMarker[] = [];
    for (const r of ov.recent_runs) {
      const ra = Number(r.params.ra), dec = Number(r.params.dec);
      if (Number.isFinite(ra) && Number.isFinite(dec)) out.push({ id: `run:${r.id}`, ra, dec, color: 'rgba(56,189,248,0.35)', shape: 'square', size: 5, label: `${String(r.params.target ?? '')} · ${String(r.params.search)}` });
    }
    for (const c of shownCandidates) out.push({ id: `cand:${c.id}`, ra: c.ra, dec: c.dec, color: CLASS_COLORS[c.class] ?? '#e5e7eb', shape: 'circle', size: 3.5, label: `${c.id} · ${t(`detect.classes.${c.class}`, { defaultValue: c.class })}` });
    for (const tg of ov.targets) out.push({ id: `target:${tg.id}`, ra: tg.ra, dec: tg.dec, color: '#22d3ee', shape: 'star', size: 4, label: tg.name });
    return out;
  }, [ov, shownCandidates, t]);

  const onSelect = (m: SkyMarker) => {
    if (!ov) return;
    const [kind, id] = [m.id.split(':')[0], m.id.slice(m.id.indexOf(':') + 1)];
    if (kind === 'target') { const tg = ov.targets.find((x) => x.id === id); if (tg) setSel({ kind: 'target', target: tg }); }
    if (kind === 'cand') { const c = ov.recent_candidates.find((x) => x.id === id); if (c) setSel({ kind: 'candidate', cand: c }); }
    if (kind === 'run') { const r = ov.recent_runs.find((x) => x.id === id); if (r) setSel({ kind: 'run', run: r }); }
  };

  const selectedId = sel ? (sel.kind === 'target' ? `target:${sel.target.id}` : sel.kind === 'candidate' ? `cand:${sel.cand.id}` : `run:${sel.run.id}`) : null;
  const totalCands = Object.values(ov?.class_counts ?? {}).reduce((a, b) => a + b, 0);
  const reviewed = (ov?.review_counts.real ?? 0) + (ov?.review_counts.artifact ?? 0) + (ov?.review_counts.unsure ?? 0);
  const running = (ov?.jobs.running ?? 0) + (ov?.jobs.queued ?? 0);

  if (error) return <div className="p-6"><div className={`${card} border-red-500/30 text-sm text-red-200 flex gap-2`}><AlertTriangle className="w-4 h-4" />{error}</div></div>;
  if (!ov) return <LoadingSpinner text={t('common.loading')} />;

  return (
    <div className="p-4 md:p-5 max-w-[1500px] mx-auto space-y-4">
      <div>
        <h1 className="text-xl md:text-2xl font-bold text-white flex items-center gap-2"><Telescope className="w-6 h-6 text-sky-400" />{t('dash.title')}</h1>
        <p className="text-sm text-gray-400 mt-1 max-w-4xl">{t('dash.subtitle')}</p>
      </div>

      {/* Live status row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className={card}>
          <div className="text-[11px] text-gray-500 flex items-center gap-1"><Satellite className="w-3.5 h-3.5" />{t('dash.irsa')}</div>
          <div className={`text-lg font-semibold ${ov.irsa.reachable ? 'text-emerald-400' : 'text-red-400'}`}>
            {ov.irsa.reachable ? t('dash.online') : t('dash.offline')}
          </div>
          <div className="text-[11px] text-gray-500">{ov.irsa.latency_ms != null ? `${ov.irsa.latency_ms} ms` : ''}</div>
        </div>
        <div className={card}>
          <div className="text-[11px] text-gray-500 flex items-center gap-1"><HardDrive className="w-3.5 h-3.5" />{t('dash.cache')}</div>
          <div className="text-lg font-semibold text-white">{ov.cache.cutouts}</div>
          <div className="text-[11px] text-gray-500">{t('dash.cacheDetail', { mb: ov.cache.size_mb, limit: ov.cache.limit_mb })}</div>
        </div>
        <div className={card}>
          <div className="text-[11px] text-gray-500 flex items-center gap-1"><Radar className="w-3.5 h-3.5" />{t('dash.searches')}</div>
          <div className="text-lg font-semibold text-white">{ov.recent_runs.length}</div>
          <div className="text-[11px] text-gray-500">{running > 0 ? t('dash.running', { n: running }) : t('dash.recentOnly')}</div>
        </div>
        <div className={card}>
          <div className="text-[11px] text-gray-500 flex items-center gap-1"><Activity className="w-3.5 h-3.5" />{t('dash.candidates')}</div>
          <div className="text-lg font-semibold text-white">{totalCands}</div>
          <div className="text-[11px] text-gray-500">{t('dash.reviewed', { n: reviewed })}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_420px] gap-4">
        <div className={card}>
          <AllSkyMap markers={markers} selectedId={selectedId} onSelect={onSelect} height={420} />
          <div className="flex flex-wrap gap-4 mt-2 text-[11px] text-gray-400">
            <span><span className="text-cyan-300">★</span> {t('dash.legend.targets')}</span>
            <span><span className="text-pink-300">●</span> {t('dash.legend.candidates')}</span>
            <span><span className="text-sky-400/60">■</span> {t('dash.legend.searches')}</span>
            <span><span className="text-yellow-300">- -</span> {t('dash.legend.ecliptic')}</span>
            <span><span className="text-violet-300">···</span> {t('dash.legend.galaxy')}</span>
          </div>
        </div>

        {/* Selection panel */}
        <div className={`${card} space-y-3`}>
          {!sel && <p className="text-sm text-gray-500">{t('dash.pick')}</p>}
          {sel?.kind === 'target' && (
            <>
              <div>
                <div className="text-[11px] text-cyan-300 uppercase tracking-wider">{t('dash.challengeTarget')}</div>
                <div className="text-lg font-semibold text-white">{sel.target.name}</div>
                <div className="text-xs font-mono text-gray-400">{formatRA(sel.target.ra)} {formatDec(sel.target.dec)}</div>
                <p className="text-xs text-gray-400 mt-1">{sel.target.note}</p>
              </div>
              {preview ? <BlinkViewer result={preview} compact autoplay /> : previewError ? <p className="text-xs text-red-300">{previewError}</p> : <JobProgressBar progress={progress} />}
              <div className="flex flex-wrap gap-2">
                <Link className="px-3 py-1.5 rounded-lg bg-sky-500/15 border border-sky-500/30 text-xs text-sky-200 flex items-center gap-1" to={`/?target=${encodeURIComponent(sel.target.name)}&fov=0.1&det=${sel.target.detector}&mode=epoch&per=4`}><Sparkles className="w-3.5 h-3.5" />Blink</Link>
                <Link className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-gray-200" to={`/detection?target=${encodeURIComponent(sel.target.name)}&search=proper_motion&fov=0.1&det=${sel.target.detector}&max=36&z=5`}>{t('detect.search.proper_motion')}</Link>
              </div>
            </>
          )}
          {sel?.kind === 'candidate' && (
            <>
              <div>
                <div className="text-[11px] uppercase tracking-wider" style={{ color: CLASS_COLORS[sel.cand.class] }}>{t(`detect.classes.${sel.cand.class}`, { defaultValue: sel.cand.class })}</div>
                <div className="text-lg font-semibold text-white font-mono">{sel.cand.id}</div>
                <div className="text-xs font-mono text-gray-400">{formatRA(sel.cand.ra)} {formatDec(sel.cand.dec)} · {sel.cand.t0_date?.slice(0, 10)}</div>
                {sel.cand.match && <p className="text-xs text-gray-300 mt-1">{sel.cand.match.name}</p>}
                <p className="text-xs text-gray-400 mt-1">{t(`detect.explain.${sel.cand.class}`, { defaultValue: '' })}</p>
              </div>
              <Link className="inline-block px-3 py-1.5 rounded-lg bg-sky-500/15 border border-sky-500/30 text-xs text-sky-200" to={`/analysis/${sel.cand.id}`}>{t('analysisLive.open')} →</Link>
            </>
          )}
          {sel?.kind === 'run' && (
            <>
              <div className="text-[11px] text-sky-300 uppercase tracking-wider">{t('dash.search')}</div>
              <div className="text-lg font-semibold text-white">{String(sel.run.params.target ?? `${sel.run.params.ra} ${sel.run.params.dec}`)}</div>
              <div className="text-xs text-gray-400">{t(`detect.search.${String(sel.run.params.search)}`)} · {sel.run.created_at.replace('T', ' ').slice(0, 16)}</div>
              <div className="text-xs text-gray-300">{t('dash.runSummary', { n: Number(sel.run.summary.n_candidates ?? 0), frames: Number(sel.run.summary.searched_frames ?? 0) })}</div>
              <Link className="inline-block px-3 py-1.5 rounded-lg bg-sky-500/15 border border-sky-500/30 text-xs text-sky-200"
                to={`/detection?target=${encodeURIComponent(String(sel.run.params.target ?? `${sel.run.params.ra} ${sel.run.params.dec}`))}&search=${String(sel.run.params.search)}&fov=${String(sel.run.params.fov)}&det=${encodeURIComponent(Array.isArray(sel.run.params.detectors) ? (sel.run.params.detectors as number[]).join(',') : 'all')}&max=${String(sel.run.params.max_frames)}&z=${String(sel.run.params.z_thresh)}${sel.run.params.pass_index != null ? `&pass=${String(sel.run.params.pass_index)}` : ''}`}>
                {t('dash.reopen')} →
              </Link>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className={card}>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">{t('dash.byClass')}</h3>
          {totalCands === 0 ? <p className="text-xs text-gray-500">{t('dash.noCandidates')} <Link className="text-sky-400 hover:underline" to="/detection">{t('nav.detection')} →</Link></p> : (
            <ul className="space-y-1">
              {Object.entries(ov.class_counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
                <li key={k} className="flex justify-between text-xs"><span style={{ color: CLASS_COLORS[k] }}>{t(`detect.classes.${k}`, { defaultValue: k })}</span><span className="font-mono text-gray-300">{n}</span></li>
              ))}
            </ul>
          )}
        </div>
        <div className={card}>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">{t('dash.recent')}</h3>
          {ov.recent_runs.length === 0 ? <p className="text-xs text-gray-500">{t('dash.noRuns')}</p> : (
            <ul className="space-y-1.5">
              {ov.recent_runs.map((r) => (
                <li key={r.id}>
                  <button onClick={() => setSel({ kind: 'run', run: r })} className="w-full text-left text-xs hover:text-white text-gray-300 flex justify-between gap-2">
                    <span className="truncate">{String(r.params.target ?? `${r.params.ra} ${r.params.dec}`)} · {t(`detect.search.${String(r.params.search)}`)}</span>
                    <span className="text-gray-500 shrink-0">{Number(r.summary.n_candidates ?? 0)} · {r.created_at.slice(5, 16).replace('T', ' ')}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className={card}>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">{t('dash.mission')}</h3>
          <ul className="text-xs text-gray-300 space-y-1">
            <li>{t('dash.fact1')}</li><li>{t('dash.fact2')}</li><li>{t('dash.fact3')}</li><li>{t('dash.fact4')}</li>
          </ul>
          <a className="text-[11px] text-sky-400 hover:underline inline-flex items-center gap-1 mt-2" href="https://irsa.ipac.caltech.edu/Missions/spherex.html" target="_blank" rel="noreferrer">IRSA SPHEREx <ExternalLink className="w-3 h-3" /></a>
        </div>
      </div>
    </div>
  );
}
