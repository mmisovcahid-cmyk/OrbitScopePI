import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CartesianGrid, ErrorBar, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from 'recharts';
import type { TooltipProps } from 'recharts';
import { Activity } from 'lucide-react';
import api from '../../services/api';
import JobProgressBar from '../common/JobProgressBar';
import { JobProgress, isAbort, runJob } from '../../lib/jobs';
import { DETECTOR_COLORS, PhotPoint, PhotometryResult, errorText, formatDec, formatRA } from '../../lib/spherex';

interface Props {
  /** Query identifying the main target (target name or ra/dec + pm), as sent to /blink. */
  targetParams: Record<string, string | number>;
  targetLabel: string;
  pick: [number, number] | null;
}

type Source = 'target' | 'pick';

const mjdToDate = (mjd: number) => new Date((mjd - 40587) * 86400000).toISOString().slice(0, 10);

export default function PhotometryPanel({ targetParams, targetLabel, pick }: Props) {
  const { t } = useTranslation();
  const [data, setData] = useState<PhotometryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showFlagged, setShowFlagged] = useState(false);
  const [measured, setMeasured] = useState<Source | null>(null);
  const ctrlRef = useRef<AbortController | null>(null);

  const targetKey = JSON.stringify(targetParams);
  useEffect(() => { setData(null); setError(null); setMeasured(null); ctrlRef.current?.abort(); }, [targetKey]);
  useEffect(() => () => ctrlRef.current?.abort(), []);

  const run = (src: Source) => {
    ctrlRef.current?.abort();
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    const params: Record<string, string | number> =
      src === 'pick' && pick ? { ra: pick[0], dec: pick[1] } : { ...targetParams };
    params.max_frames = 96; // dense spectral sampling (e.g. the 3.3 um CH4 band of T dwarfs)
    delete params.fov; delete params.mode; delete params.per_epoch; delete params.detector; delete params.pass_index;
    delete params.wl_min; delete params.wl_max;
    setLoading(true); setError(null); setProgress(null); setMeasured(src);
    runJob<PhotometryResult>('photometry', params, setProgress, ctrl.signal)
      .then((res) => setData(res))
      .catch((e) => {
        if (isAbort(e) || ctrl.signal.aborted) return;
        setData(null);
        setError(errorText(e, t('blink.errors.timeout'), t('blink.errors.network', { url: api.defaults.baseURL })));
      })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
  };

  const series = useMemo(() => {
    const pts = (data?.points ?? []).filter((p) => p.flux_mjy != null && p.wavelength_um != null && (showFlagged || !p.flagged));
    const byDet: Record<number, PhotPoint[]> = {};
    for (const p of pts) (byDet[p.detector] ??= []).push(p);
    return Object.entries(byDet).map(([det, list]) => ({
      det: Number(det),
      color: DETECTOR_COLORS[(Number(det) - 1) % DETECTOR_COLORS.length],
      spectrum: list.map((p) => ({ x: p.wavelength_um, y: p.flux_mjy, err: p.err_mjy ?? 0, p })),
      light: list.map((p) => ({ x: p.mjd, y: p.flux_mjy, err: p.err_mjy ?? 0, p })),
    }));
  }, [data, showFlagged]);

  const nFlagged = (data?.points ?? []).filter((p) => p.flagged).length;

  const tooltip = ({ active, payload }: TooltipProps<number, string>) => {
    const p = (payload?.[0]?.payload as { p?: PhotPoint } | undefined)?.p;
    if (!active || !p) return null;
    return (
      <div className="rounded-lg bg-[#0b1224] border border-white/10 px-2 py-1.5 text-[11px] text-gray-200 font-mono">
        <div>{p.date.slice(0, 16).replace('T', ' ')} · D{p.detector}</div>
        <div>λ {p.wavelength_um?.toFixed(3)} µm</div>
        <div>{p.flux_mjy?.toFixed(3)} ± {p.err_mjy?.toFixed(3)} mJy</div>
        {p.flagged && <div className="text-amber-300">{p.saturated ? t('blink.phot.saturated') : t('blink.phot.flagged')}</div>}
        <div className="text-gray-500">{p.obs_id}</div>
      </div>
    );
  };

  const btn = 'px-3 py-1.5 rounded-lg text-xs border transition-colors disabled:opacity-40';

  return (
    <div className="rounded-2xl border border-white/[0.08] bg-[#0a1020]/80 p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
          <Activity className="w-3.5 h-3.5" /> {t('blink.phot.title')}
        </h3>
        <div className="flex flex-wrap gap-2">
          <button className={`${btn} border-sky-500/40 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20`} disabled={loading} onClick={() => run('target')}>
            {t('blink.phot.measureTarget', { name: targetLabel })}
          </button>
          <button className={`${btn} border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-300 hover:bg-fuchsia-500/20`} disabled={loading || !pick} onClick={() => run('pick')}
            title={pick ? '' : t('blink.phot.pickHint')}>
            {t('blink.phot.measurePick')}
          </button>
        </div>
      </div>
      <p className="text-[11px] text-gray-500">
        {t('blink.phot.explain')}
        {pick && <span className="text-fuchsia-300"> {t('blink.phot.picked')}: {formatRA(pick[0])} {formatDec(pick[1])}</span>}
      </p>

      {loading && (
        <JobProgressBar progress={progress} onCancel={() => { ctrlRef.current?.abort(); setLoading(false); }} />
      )}
      {!loading && error && <div className="text-xs text-red-300">{error}</div>}

      {!loading && data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-gray-400">
            <span>
              {measured === 'pick' ? t('blink.phot.picked') : (data.position.name || targetLabel)} ·{' '}
              {t('blink.phot.summary', { good: data.n_good, total: data.n_points, ap: data.aperture_arcsec })}
            </span>
            {nFlagged > 0 && (
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={showFlagged} onChange={(e) => setShowFlagged(e.target.checked)} className="accent-amber-400" />
                {t('blink.phot.showFlagged', { n: nFlagged })}
              </label>
            )}
          </div>
          {series.length === 0 ? (
            <p className="text-xs text-amber-300">{t('blink.phot.noGood')}</p>
          ) : (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <div>
                <div className="text-[11px] text-gray-400 mb-1">{t('blink.phot.spectrum')}</div>
                <div className="h-60">
                  <ResponsiveContainer width="100%" height="100%">
                    <ScatterChart margin={{ top: 5, right: 10, bottom: 20, left: 0 }}>
                      <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                      <XAxis type="number" dataKey="x" domain={[0.7, 5.1]} ticks={[0.75, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]}
                        tick={{ fill: '#9ca3af', fontSize: 10 }}
                        label={{ value: 'λ (µm)', position: 'insideBottom', offset: -10, fill: '#9ca3af', fontSize: 10 }} />
                      <YAxis type="number" dataKey="y" tick={{ fill: '#9ca3af', fontSize: 10 }} width={52}
                        label={{ value: 'mJy', angle: -90, position: 'insideLeft', fill: '#9ca3af', fontSize: 10 }} />
                      <Tooltip content={tooltip} cursor={{ stroke: 'rgba(255,255,255,0.2)' }} />
                      <Legend wrapperStyle={{ fontSize: 10 }} verticalAlign="top" height={20} />
                      {series.map((s) => (
                        <Scatter key={s.det} name={`D${s.det}`} data={s.spectrum} fill={s.color} isAnimationActive={false}>
                          <ErrorBar dataKey="err" direction="y" stroke={s.color} strokeOpacity={0.5} width={0} />
                        </Scatter>
                      ))}
                    </ScatterChart>
                  </ResponsiveContainer>
                </div>
              </div>
              <div>
                <div className="text-[11px] text-gray-400 mb-1">{t('blink.phot.lightCurve')}</div>
                <div className="h-60">
                  <ResponsiveContainer width="100%" height="100%">
                    <ScatterChart margin={{ top: 5, right: 10, bottom: 20, left: 0 }}>
                      <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                      <XAxis type="number" dataKey="x" domain={['dataMin - 10', 'dataMax + 10']} tickFormatter={mjdToDate}
                        tick={{ fill: '#9ca3af', fontSize: 10 }} />
                      <YAxis type="number" dataKey="y" tick={{ fill: '#9ca3af', fontSize: 10 }} width={52}
                        label={{ value: 'mJy', angle: -90, position: 'insideLeft', fill: '#9ca3af', fontSize: 10 }} />
                      <Tooltip content={tooltip} cursor={{ stroke: 'rgba(255,255,255,0.2)' }} />
                      <Legend wrapperStyle={{ fontSize: 10 }} verticalAlign="top" height={20} />
                      {series.map((s) => (
                        <Scatter key={s.det} name={`D${s.det}`} data={s.light} fill={s.color} isAnimationActive={false}>
                          <ErrorBar dataKey="err" direction="y" stroke={s.color} strokeOpacity={0.5} width={0} />
                        </Scatter>
                      ))}
                    </ScatterChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          )}
          <p className="text-[10px] text-gray-600">{data.units} · {t('blink.phot.lvfNote')}</p>
        </>
      )}
    </div>
  );
}
