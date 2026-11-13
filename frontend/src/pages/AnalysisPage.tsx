import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, XCircle, HelpCircle, Download, Eye, Database, AlertTriangle } from 'lucide-react';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { spherexService } from '../services';
import api from '../services/api';
import { CLASS_COLORS, Candidate, ReviewStatus, errorText, formatDec, formatRA } from '../lib/spherex';

interface Run { id: string; created_at: string; params: Record<string, unknown>; summary: Record<string, unknown> }

const card = 'rounded-2xl border border-white/[0.08] bg-[#0a1020]/80 p-4';

/** Detail page of one saved (real-data) candidate: /analysis/:id */
export default function AnalysisPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const [cand, setCand] = useState<(Candidate & { run?: Run | null }) | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    spherexService.candidate(id)
      .then((res) => { setCand(res.data?.data ?? null); setNote(res.data?.data?.note ?? ''); })
      .catch((e) => setError(errorText(e, t('blink.errors.timeout'), t('blink.errors.network', { url: api.defaults.baseURL }))));
  }, [id, t]);

  const review = async (status: ReviewStatus) => {
    if (!cand) return;
    setSaving(true);
    try {
      const res = await spherexService.review(cand.id, status, note);
      setCand({ ...cand, ...res.data?.data });
    } catch (e) {
      setError(errorText(e, t('blink.errors.timeout')));
    } finally {
      setSaving(false);
    }
  };

  if (error) {
    return (
      <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-3">
        <Link to="/detection" className="text-xs text-sky-400 flex items-center gap-1"><ArrowLeft className="w-3.5 h-3.5" />{t('nav.detection')}</Link>
        <div className={`${card} border-red-500/30 text-sm text-red-200 flex gap-2`}><AlertTriangle className="w-4 h-4 shrink-0" />{error}</div>
      </div>
    );
  }
  if (!cand) return <LoadingSpinner text={t('common.loading')} />;

  const p = (cand.run?.params ?? {}) as Record<string, unknown>;
  const dets = Array.isArray(p.detectors) ? (p.detectors as number[]).join(',') : 'all';
  const blinkQ = new URLSearchParams({
    ra: cand.ra.toFixed(6), dec: cand.dec.toFixed(6), fov: '0.1', det: dets,
    ...(cand.search === 'asteroids'
      ? { mode: 'pass', max: String(p.max_frames ?? 36), ...(p.pass_index != null ? { pass: String(p.pass_index) } : {}) }
      : { mode: 'epoch', per: '4' }),
  });
  const status = (cand.status ?? 'unreviewed') as ReviewStatus;
  const color = CLASS_COLORS[cand.class] ?? '#e5e7eb';
  const rate = cand.search === 'asteroids' ? `${cand.rate_arcsec_per_hour.toFixed(1)}″/h` : `${cand.rate_arcsec_per_year.toFixed(2)}″/yr`;
  const btn = (s: ReviewStatus, Icon: typeof CheckCircle2, cls: string) => (
    <button disabled={saving} onClick={() => review(s)}
      className={`px-3 py-1.5 rounded-lg text-xs border flex items-center gap-1 ${status === s ? `${cls} bg-white/10 border-white/20` : 'text-gray-400 border-white/10 hover:text-gray-200'}`}>
      <Icon className="w-4 h-4" /> {t(`detect.review.${s}`)}
    </button>
  );

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
      <Link to="/detection" className="text-xs text-sky-400 flex items-center gap-1"><ArrowLeft className="w-3.5 h-3.5" />{t('nav.detection')}</Link>

      <div className={card}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-white font-mono">{cand.id}</h1>
            <div className="text-sm mt-1" style={{ color }}>{t(`detect.classes.${cand.class}`, { defaultValue: cand.class })} · {t('detect.score')} {cand.score}</div>
            <p className="text-xs text-gray-400 mt-2 max-w-2xl">{t(`detect.explain.${cand.class}`, { defaultValue: '' })}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to={`/?${blinkQ}`} className="px-3 py-1.5 rounded-lg bg-sky-500/15 border border-sky-500/30 text-xs text-sky-200 flex items-center gap-1"><Eye className="w-4 h-4" /> Blink</Link>
            <a href={spherexService.exportUrl(cand.id)} className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-gray-200 flex items-center gap-1"><Download className="w-4 h-4" /> CSV</a>
            {cand.match?.type === 'known_sso' && (
              <Link to={`/catalog?q=${encodeURIComponent(cand.match.name.split(' (')[0])}`} className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-gray-200 flex items-center gap-1"><Database className="w-4 h-4" /> JPL</Link>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className={card}>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">{t('analysisLive.measurement')}</h3>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            <dt className="text-gray-500">RA / Dec</dt><dd className="font-mono text-gray-200">{formatRA(cand.ra)} {formatDec(cand.dec)}</dd>
            <dt className="text-gray-500">{t('analysisLive.epoch')}</dt><dd className="text-gray-200">{cand.t0_date?.replace('T', ' ').replace('Z', ' UTC')}</dd>
            <dt className="text-gray-500">{t('detect.col.rate')}</dt><dd className="text-gray-200">{rate}{cand.position_angle_deg != null ? ` · PA ${cand.position_angle_deg}°` : ''}</dd>
            <dt className="text-gray-500">{t('detect.fitRms')}</dt><dd className="text-gray-200">{cand.rms_px} px</dd>
            <dt className="text-gray-500">{t('analysisLive.detections')}</dt><dd className="text-gray-200">{cand.n_detections} · {cand.n_detectors} {t('analysisLive.detectors')}</dd>
            <dt className="text-gray-500">S/N</dt><dd className="text-gray-200">{cand.mean_z}</dd>
            {cand.match && (<>
              <dt className="text-gray-500">{t('detect.col.match')}</dt>
              <dd className="text-gray-200">{cand.match.name} ({cand.match.sep_arcsec}″)</dd>
            </>)}
          </dl>
        </div>
        <div className={card}>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">{t('analysisLive.review')}</h3>
          <div className="flex flex-wrap gap-2">
            {btn('real', CheckCircle2, 'text-emerald-400')}
            {btn('artifact', XCircle, 'text-red-400')}
            {btn('unsure', HelpCircle, 'text-amber-300')}
          </div>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} maxLength={2000}
            placeholder={t('analysisLive.notePlaceholder')}
            className="mt-3 w-full px-3 py-2 rounded-lg bg-[#0b1224] border border-white/10 text-xs text-white" />
          <p className="text-[10px] text-gray-600 mt-1">{t('analysisLive.noteHint')}</p>
          {cand.run && (
            <p className="text-[10px] text-gray-500 mt-3 font-mono">{cand.run.id} · {String(cand.run.params.search)} · {cand.run.created_at}</p>
          )}
        </div>
      </div>

      <div className={card}>
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">{t('analysisLive.astrometry')}</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead className="text-gray-500 border-b border-white/5">
              <tr><th className="text-left py-1">UTC</th><th>D</th><th className="text-left">RA (°)</th><th className="text-left">Dec (°)</th><th>S/N</th><th>{t('analysisLive.onStar')}</th></tr>
            </thead>
            <tbody>
              {cand.detections.map((d) => (
                <tr key={d.frame} className="border-b border-white/[0.03] text-gray-300">
                  <td className="py-1">{d.date.replace('T', ' ').replace('Z', '')}</td><td className="text-center">{d.detectors.join('/')}</td>
                  <td>{d.ra.toFixed(6)}</td><td>{d.dec.toFixed(6)}</td><td className="text-center">{d.z}</td>
                  <td className="text-center">{d.on_star ? '●' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[10px] text-gray-600 mt-2">{t('detect.disclaimer')}</p>
      </div>
    </div>
  );
}
