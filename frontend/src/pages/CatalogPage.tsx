import { useCallback, useEffect, useState } from 'react';
import { SnapshotNote } from '../components/common/OfflineBanner';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { Search, Database, Globe, Compass, AlertTriangle, ExternalLink, Crosshair, Calendar, Radar } from 'lucide-react';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { catalogService } from '../services';
import api from '../services/api';
import { errorText, formatDec, formatRA } from '../lib/spherex';

interface CloseApproach { date: string; body: string; distance_au: number | null; distance_ld: number | null; velocity_km_s: number | null }
interface SbdbObject {
  designation: string; name: string; spkid: string; kind: 'asteroid' | 'comet'; numbered: boolean;
  offline_snapshot?: { saved_at: string };
  orbit_class: { code?: string; name?: string }; neo: boolean; pha: boolean;
  elements: Record<string, number | null>; physical: Record<string, number | string | null>;
  orbit_quality: Record<string, string | number | null>;
  discovery: { text?: string; date?: string; who?: string; location?: string } | null;
  close_approaches: { upcoming: CloseApproach[]; recent: CloseApproach[]; total: number };
  source: string; url: string;
}
interface EphemRow { time_utc: string; ra_deg: number; dec_deg: number; magnitude: number | null; r_au: number | null; delta_au: number | null; elongation_deg: number | null; phase_deg: number | null }
interface Ephem { resolved_name: string; rows: EphemRow[]; source: string }
interface FieldObj { name: string; kind: string; ra: number; dec: number; vmag: number | null; separation_arcmin: number; rate_arcsec_per_hour: number }

const card = 'rounded-xl border border-white/5 bg-white/[0.02] p-5';
const input = 'w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500';
const POPULAR = ['1 Ceres', '4 Vesta', '433 Eros', '99942 Apophis', '101955 Bennu', '90377 Sedna', '1P/Halley', '134340 Pluto'];
const fmt = (v: number | string | null | undefined, digits = 4) =>
  v === null || v === undefined || v === '' ? '—' : typeof v === 'number' ? Number(v.toFixed(digits)).toString() : String(v);

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-1.5 border-b border-white/5 last:border-0 text-xs">
      <span className="text-gray-400">{label}</span><span className="font-mono text-white text-right">{value}</span>
    </div>
  );
}

export default function CatalogPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get('q') ?? '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [obj, setObj] = useState<SbdbObject | null>(null);
  const [matches, setMatches] = useState<{ designation: string; name: string }[] | null>(null);
  const [ephem, setEphem] = useState<Ephem | null>(null);
  const [ephemError, setEphemError] = useState<string | null>(null);

  // Field search (known objects in a sky field at a time)
  const [fRa, setFRa] = useState('9.6915');
  const [fDec, setFDec] = useState('4.0152');
  const [fRad, setFRad] = useState('0.3');
  const [fTime, setFTime] = useState('2025-06-24T11:10');
  const [field, setField] = useState<FieldObj[] | null>(null);
  const [fieldLoading, setFieldLoading] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);

  const netMsg = t('blink.errors.network', { url: api.defaults.baseURL });

  const lookup = useCallback(async (q: string) => {
    if (!q.trim()) return;
    setLoading(true); setError(null); setObj(null); setMatches(null); setEphem(null); setEphemError(null);
    try {
      const res = await catalogService.getObject(q.trim());
      const d = res.data?.data;
      if (d?.matches) { setMatches(d.matches); return; }
      setObj(d as SbdbObject);
      catalogService.getEphemeris(d.designation, 7)
        .then((r) => setEphem(r.data?.data?.rows ? r.data.data : null))
        .catch((e) => setEphemError(errorText(e, t('blink.errors.timeout'), netMsg)));
    } catch (e) {
      setError(errorText(e, t('blink.errors.timeout'), netMsg));
    } finally {
      setLoading(false);
    }
  }, [t, netMsg]);

  useEffect(() => {
    const q = params.get('q');
    if (q) { setQuery(q); lookup(q); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.toString()]);

  const submit = (q: string) => setParams({ q });

  const searchField = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setFieldLoading(true); setFieldError(null); setField(null);
    try {
      const res = await catalogService.getField(Number(fRa), Number(fDec), Number(fRad), fTime || undefined);
      setField(res.data?.data?.objects ?? []);
    } catch (err) {
      setFieldError(errorText(err, t('blink.errors.timeout'), netMsg));
    } finally {
      setFieldLoading(false);
    }
  };

  const el = obj?.elements ?? {};
  const ph = obj?.physical ?? {};
  const oq = obj?.orbit_quality ?? {};
  const now = ephem?.rows[0];

  return (
    <div className="space-y-6 p-4 md:p-6 max-w-6xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Database className="w-6 h-6 text-blue-400" /> {t('catalog.title')}
        </h1>
        <p className="text-sm text-gray-500 mt-1">{t('catalogLive.subtitle')}</p>
      </div>

      <div className={card}>
        <form onSubmit={(e) => { e.preventDefault(); submit(query); }} className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-gray-400 absolute left-3.5 top-3" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('catalogLive.placeholder')} className={`${input} pl-10`} />
          </div>
          <button type="submit" disabled={loading} className="px-6 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-sm font-medium text-white disabled:opacity-50">
            {loading ? t('common.loading') : t('catalog.search.search')}
          </button>
        </form>
        <div className="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t border-white/5">
          <span className="text-xs text-gray-500">{t('catalogLive.popular')}</span>
          {POPULAR.map((name) => (
            <button key={name} type="button" onClick={() => { setQuery(name); submit(name); }}
              className="text-xs px-2.5 py-1 rounded bg-white/5 hover:bg-white/10 text-blue-400 border border-white/5">{name}</button>
          ))}
        </div>
      </div>

      {loading && <LoadingSpinner text={t('common.loading')} />}
      {error && <div className={`${card} border-red-500/30 text-sm text-red-200 flex gap-2`}><AlertTriangle className="w-4 h-4 shrink-0" />{error}</div>}

      {matches && (
        <div className={card}>
          <h3 className="text-sm font-semibold text-white mb-2">{t('catalogLive.matches', { n: matches.length })}</h3>
          <div className="flex flex-wrap gap-2">
            {matches.map((m) => (
              <button key={m.designation} onClick={() => { setQuery(m.designation); submit(m.designation); }}
                className="text-xs px-2.5 py-1 rounded bg-white/5 hover:bg-white/10 text-blue-300 border border-white/10">{m.name}</button>
            ))}
          </div>
        </div>
      )}

      {obj && !loading && (
        <div className="space-y-6">
          <div className={`${card} flex flex-col md:flex-row md:items-center justify-between gap-4`}>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-2xl font-bold text-white">{obj.name}</h2>
                <span className="px-2.5 py-0.5 rounded-full text-xs bg-blue-500/10 text-blue-400 border border-blue-500/20">{t(`catalogLive.kind.${obj.kind}`)}</span>
                {obj.orbit_class?.name && <span className="px-2.5 py-0.5 rounded-full text-xs bg-violet-500/10 text-violet-300 border border-violet-500/20">{obj.orbit_class.name}</span>}
                {obj.neo && <span className="px-2.5 py-0.5 rounded-full text-xs bg-amber-500/10 text-amber-300 border border-amber-500/30">NEO</span>}
                {obj.pha && <span className="px-2.5 py-0.5 rounded-full text-xs bg-red-500/10 text-red-300 border border-red-500/30">PHA</span>}
              </div>
              <p className="text-xs text-gray-400 mt-1">
                {t('catalogLive.designation')}: <span className="font-mono text-gray-300">{obj.designation}</span> · SPK-ID <span className="font-mono text-gray-300">{obj.spkid}</span>
              </p>
              {obj.discovery?.text && <p className="text-xs text-gray-400 mt-1">{obj.discovery.text}</p>}
              <SnapshotNote snapshot={obj.offline_snapshot} />
            </div>
            <a href={obj.url} target="_blank" rel="noreferrer" className="text-xs text-sky-400 hover:text-sky-300 flex items-center gap-1 shrink-0">
              {obj.source} <ExternalLink className="w-3 h-3" />
            </a>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className={card}>
              <h3 className="text-base font-semibold text-white mb-3 flex items-center gap-2"><Compass className="w-4 h-4 text-blue-400" />{t('catalog.detail.orbital')}</h3>
              <Row label={`${t('catalog.detail.semiMajorAxis')} (a)`} value={`${fmt(el.a_au)} AU`} />
              <Row label={`${t('catalog.detail.eccentricity')} (e)`} value={fmt(el.e, 5)} />
              <Row label={`${t('catalog.detail.inclination')} (i)`} value={`${fmt(el.i_deg)}°`} />
              <Row label={`${t('catalog.detail.perihelion')} (q)`} value={`${fmt(el.q_au)} AU`} />
              <Row label={`${t('catalog.detail.aphelion')} (Q)`} value={`${fmt(el.ad_au)} AU`} />
              <Row label={t('catalog.detail.orbitalPeriod')} value={`${fmt(el.period_yr, 3)} ${t('catalog.detail.years')}`} />
              <Row label={`${t('catalog.detail.lonAscNode')} (Ω)`} value={`${fmt(el.om_deg)}°`} />
              <Row label={`${t('catalog.detail.argPerihelion')} (ω)`} value={`${fmt(el.w_deg)}°`} />
              <Row label={t('catalogLive.moid')} value={`${fmt(el.moid_au)} AU`} />
              <Row label={t('catalogLive.tisserand')} value={fmt(el.t_jup, 3)} />
            </div>
            <div className={card}>
              <h3 className="text-base font-semibold text-white mb-3 flex items-center gap-2"><Globe className="w-4 h-4 text-emerald-400" />{t('catalog.detail.physical')}</h3>
              <Row label={t('catalog.detail.diameter')} value={ph.diameter_km != null ? `${fmt(ph.diameter_km, 3)} km` : '—'} />
              <Row label={`${t('catalog.detail.absoluteMag')} (H)`} value={fmt(ph.H, 2)} />
              <Row label={t('catalog.detail.albedo')} value={fmt(ph.albedo, 3)} />
              <Row label={t('catalogLive.rotation')} value={ph.rotation_h != null ? `${fmt(ph.rotation_h, 3)} h` : '—'} />
              <Row label={t('catalogLive.spectral')} value={fmt(ph.spectral_type)} />
              <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wider mt-4 mb-1">{t('catalogLive.orbitQuality')}</h4>
              <Row label={t('catalogLive.conditionCode')} value={fmt(oq.condition_code)} />
              <Row label={t('catalogLive.observations')} value={fmt(oq.n_obs)} />
              <Row label={t('catalogLive.arc')} value={`${fmt(oq.first_obs)} → ${fmt(oq.last_obs)}`} />
            </div>
          </div>

          {/* Current position & ephemeris (JPL Horizons) */}
          <div className={card}>
            <h3 className="text-base font-semibold text-white mb-1 flex items-center gap-2"><Crosshair className="w-4 h-4 text-sky-400" />{t('catalogLive.ephemTitle')}</h3>
            <p className="text-[11px] text-gray-500 mb-3">{t('catalogLive.ephemNote')}</p>
            {ephemError && <p className="text-xs text-red-300">{ephemError}</p>}
            {!ephem && !ephemError && <LoadingSpinner />}
            {now && (
              <p className="text-sm text-gray-200 mb-3">
                {t('catalogLive.now')}: <span className="font-mono">{formatRA(now.ra_deg)} {formatDec(now.dec_deg)}</span>
                {now.magnitude != null && <> · {t('catalogLive.mag')} <span className="font-mono">{now.magnitude.toFixed(1)}</span></>}
                {now.delta_au != null && <> · {t('catalogLive.fromEarth')} <span className="font-mono">{now.delta_au.toFixed(3)} AU</span></>}
              </p>
            )}
            {ephem && (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-gray-500 border-b border-white/5">
                    <tr><th className="text-left py-1">UTC</th><th className="text-left">RA</th><th className="text-left">Dec</th><th>{t('catalogLive.mag')}</th><th>r (AU)</th><th>Δ (AU)</th><th>{t('catalogLive.elongation')}</th></tr>
                  </thead>
                  <tbody>
                    {ephem.rows.map((r) => (
                      <tr key={r.time_utc} className="border-b border-white/[0.03] font-mono text-gray-300">
                        <td className="py-1">{r.time_utc}</td><td>{formatRA(r.ra_deg)}</td><td>{formatDec(r.dec_deg)}</td>
                        <td className="text-center">{fmt(r.magnitude, 2)}</td><td className="text-center">{fmt(r.r_au, 3)}</td>
                        <td className="text-center">{fmt(r.delta_au, 3)}</td><td className="text-center">{fmt(r.elongation_deg, 1)}°</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-[10px] text-gray-600 mt-2">{ephem.source} · {ephem.resolved_name}</p>
              </div>
            )}
          </div>

          {(obj.close_approaches.upcoming.length > 0 || obj.close_approaches.recent.length > 0) && (
            <div className={card}>
              <h3 className="text-base font-semibold text-white mb-3 flex items-center gap-2"><Calendar className="w-4 h-4 text-amber-400" />{t('catalogLive.approaches', { n: obj.close_approaches.total })}</h3>
              <table className="w-full text-xs">
                <thead className="text-gray-500 border-b border-white/5">
                  <tr><th className="text-left py-1">{t('catalogLive.date')}</th><th className="text-left">{t('catalogLive.body')}</th><th className="text-left">{t('catalogLive.distance')}</th><th className="text-left">km/s</th></tr>
                </thead>
                <tbody>
                  {[...obj.close_approaches.recent, ...obj.close_approaches.upcoming].map((ca) => (
                    <tr key={`${ca.date}-${ca.body}`} className="border-b border-white/[0.03] font-mono">
                      <td className="py-1 text-gray-300">{ca.date}</td><td className="text-gray-400">{ca.body}</td>
                      <td className="text-blue-300">{fmt(ca.distance_au, 5)} AU{ca.body === 'Earth' && ca.distance_ld != null ? ` (${ca.distance_ld} LD)` : ''}</td>
                      <td className="text-gray-400">{fmt(ca.velocity_km_s, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Field search */}
      <div className={card}>
        <h3 className="text-base font-semibold text-white mb-1 flex items-center gap-2"><Radar className="w-4 h-4 text-cyan-400" />{t('catalogLive.fieldTitle')}</h3>
        <p className="text-[11px] text-gray-500 mb-3">{t('catalogLive.fieldNote')}</p>
        <form onSubmit={searchField} className="grid grid-cols-2 md:grid-cols-5 gap-2 items-end">
          <label className="text-[11px] text-gray-400">RA (°)<input className={input} value={fRa} onChange={(e) => setFRa(e.target.value)} inputMode="decimal" /></label>
          <label className="text-[11px] text-gray-400">Dec (°)<input className={input} value={fDec} onChange={(e) => setFDec(e.target.value)} inputMode="decimal" /></label>
          <label className="text-[11px] text-gray-400">{t('catalogLive.radius')}<input className={input} value={fRad} onChange={(e) => setFRad(e.target.value)} inputMode="decimal" /></label>
          <label className="text-[11px] text-gray-400">{t('catalogLive.timeUtc')}<input className={input} value={fTime} onChange={(e) => setFTime(e.target.value)} placeholder="2025-06-24T11:10" /></label>
          <button type="submit" disabled={fieldLoading} className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-sm text-white disabled:opacity-50">
            {fieldLoading ? t('common.loading') : t('catalog.search.search')}
          </button>
        </form>
        {fieldLoading && <p className="text-[11px] text-gray-500 mt-2">{t('catalogLive.fieldSlow')}</p>}
        {fieldError && <p className="text-xs text-red-300 mt-2">{fieldError}</p>}
        {field && (
          field.length === 0 ? <p className="text-xs text-gray-500 mt-3">{t('catalogLive.fieldNone')}</p> : (
            <table className="w-full text-xs mt-3">
              <thead className="text-gray-500 border-b border-white/5">
                <tr><th className="text-left py-1">{t('catalogLive.object')}</th><th>V</th><th>{t('catalogLive.sep')}</th><th>{t('detect.col.rate')}</th><th className="text-left">RA / Dec</th><th /></tr>
              </thead>
              <tbody>
                {field.map((o) => (
                  <tr key={o.name} className="border-b border-white/[0.03]">
                    <td className="py-1 text-gray-200">{o.name}</td><td className="text-center font-mono">{fmt(o.vmag, 1)}</td>
                    <td className="text-center font-mono">{o.separation_arcmin}′</td><td className="text-center font-mono">{o.rate_arcsec_per_hour}″/h</td>
                    <td className="font-mono text-gray-400">{formatRA(o.ra)} {formatDec(o.dec)}</td>
                    <td><button onClick={() => { const d = o.name.split(' (')[0].split(' ')[0]; setQuery(d); submit(d); }} className="text-sky-400 hover:text-sky-300">{t('catalogLive.details')}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
        <p className="text-[11px] text-gray-500 mt-3">
          {t('catalogLive.toDetection')}{' '}
          <Link className="text-sky-400 hover:underline" to={`/detection?target=${encodeURIComponent(`${fRa} ${fDec}`)}&search=asteroids&fov=0.3&det=1%2C4&max=36&z=5`}>{t('nav.detection')} →</Link>
        </p>
      </div>
    </div>
  );
}
