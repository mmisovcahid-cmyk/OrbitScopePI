import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Orbit, AlertTriangle, BookOpen, Sigma, Telescope } from 'lucide-react';
import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts';
import type { TooltipProps } from 'recharts';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { planetxService } from '../services';
import api from '../services/api';
import { errorText } from '../lib/spherex';

interface ETNO {
  designation: string; name: string; a_au: number; e: number | null; i_deg: number | null; q_au: number; ad_au: number | null;
  om_deg: number; w_deg: number; varpi_deg: number; H: number | null; in_sample: boolean;
  in_literature?: boolean; condition_code?: string | null;
}
interface Rayleigh { n: number; mean_deg: number; R: number; Z: number; p: number }
interface SampleStats { n: number; varpi: Rayleigh; node: Rayleigh; argperi: Rayleigh; missing?: number }
interface Clustering {
  objects: ETNO[]; selection: { min_a_au: number; min_q_au: number; max_condition_code?: number; n_total?: number };
  varpi: Rayleigh; node: Rayleigh; argperi: Rayleigh; source: string; missing?: number;
  literature?: SampleStats;
}

const fmtP = (p: number) => (p < 0.001 ? p.toExponential(1) : p.toFixed(3));

// Literature values (Brown & Batygin 2021, AJ 162:219) - not measured by OrbitScope.
const PREDICTIONS = [
  { key: 'mass', value: '6.2 (+2.2 / −1.3) M⊕' },
  { key: 'a', value: '380 (+140 / −80) AU' },
  { key: 'q', value: '300 (+85 / −60) AU' },
  { key: 'i', value: '16 ± 5°' },
  { key: 'period', value: '≈ 7 400 yr (a = 380 AU)' },
];

const EVIDENCE = [
  { key: 'orbitalClustering', strength: 'strong', year: 2016 },
  { key: 'perihelionDetachment', strength: 'strong', year: 2014 },
  { key: 'solarObliquity', strength: 'moderate', year: 2016 },
  { key: 'retrogradeOrbits', strength: 'moderate', year: 2016 },
  { key: 'kuiperCliff', strength: 'suggestive', year: 2001 },
];

const STRENGTH_COLORS: Record<string, string> = {
  strong: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  moderate: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
  suggestive: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
};

const card = 'rounded-xl border border-white/5 bg-white/[0.02] p-5';

function TnoTooltip({ active, payload }: TooltipProps<number, string>) {
  const o = (payload?.[0]?.payload as { o?: ETNO } | undefined)?.o;
  if (!active || !o) return null;
  return (
    <div className="rounded-lg bg-[#0b1224] border border-white/10 px-2 py-1.5 text-[11px] text-gray-200 font-mono">
      <div className="font-sans font-semibold">{o.name}</div>
      <div>a {o.a_au.toFixed(0)} AU · q {o.q_au.toFixed(1)} AU · i {o.i_deg?.toFixed(1) ?? '—'}°</div>
      <div>ϖ {o.varpi_deg.toFixed(1)}° · Ω {o.om_deg.toFixed(1)}° · ω {o.w_deg.toFixed(1)}°</div>
    </div>
  );
}

export default function PlanetXPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<Clustering | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    planetxService.getClustering()
      .then((res) => setData(res.data?.data ?? null))
      .catch((e) => setError(errorText(e, t('blink.errors.timeout'), t('blink.errors.network', { url: api.defaults.baseURL }))));
  }, [t]);

  const sample = data?.objects.filter((o) => o.in_sample) ?? [];
  // Perihelion directions projected on the ecliptic: (q cos varpi, q sin varpi)
  const toPeri = (o: ETNO) => ({
    x: o.q_au * Math.cos((o.varpi_deg * Math.PI) / 180), y: o.q_au * Math.sin((o.varpi_deg * Math.PI) / 180), o,
  });
  const peri = sample.filter((o) => !o.in_literature).map(toPeri);
  const periLit = sample.filter((o) => o.in_literature).map(toPeri);
  const lim = Math.ceil(Math.max(50, ...sample.map((o) => o.q_au)) / 10) * 10 + 10;
  const meanDir = data?.varpi.mean_deg ?? 0;

  const verdict = (p: number) => (p < 0.01 ? 'strong' : p < 0.05 ? 'weak' : 'none');

  return (
    <div className="space-y-6 p-4 md:p-6 max-w-6xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Orbit className="w-7 h-7 text-violet-400" /> {t('planetx.title')}
        </h1>
        <p className="text-sm text-gray-500 mt-1">{t('planetxLive.subtitle')}</p>
      </div>

      <div className="flex gap-3 p-4 rounded-xl bg-amber-500/5 border border-amber-500/15">
        <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
        <p className="text-sm text-amber-300/80">{t('planetx.disclaimer')}</p>
      </div>

      {/* Live clustering test */}
      <div className={card}>
        <h2 className="text-lg font-semibold text-white mb-1 flex items-center gap-2"><Sigma className="w-5 h-5 text-violet-400" />{t('planetxLive.testTitle')}</h2>
        <p className="text-xs text-gray-500 mb-4">{t('planetxLive.testIntro')}</p>
        {!data && !error && <LoadingSpinner text={t('planetxLive.loading')} />}
        {error && <p className="text-sm text-red-300">{error}</p>}
        {data && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
              {([['varpi', 'ϖ'], ['node', 'Ω'], ['argperi', 'ω']] as const).map(([k, sym]) => {
                const r = data[k];
                const v = verdict(r.p);
                return (
                  <div key={k} className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                    <div className="text-[11px] text-gray-400">{t(`planetxLive.angle.${k}`)} ({sym})</div>
                    <div className="text-lg font-semibold text-white">p = {fmtP(r.p)}</div>
                    <div className="text-[11px] text-gray-400 font-mono">n={r.n} · R̄={r.R} · {t('planetxLive.mean')} {r.mean_deg}°</div>
                    <div className={`text-[11px] mt-1 ${v === 'strong' ? 'text-emerald-400' : v === 'weak' ? 'text-amber-300' : 'text-gray-400'}`}>
                      {t(`planetxLive.verdict.${v}`)}
                    </div>
                  </div>
                );
              })}
            </div>
            {data.literature && (
              <div className="mb-4 rounded-lg border border-violet-500/20 bg-violet-500/5 p-3">
                <div className="text-sm text-white font-semibold mb-2">{t('planetxLive.compareTitle')}</div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="text-gray-500"><tr>
                      <th className="text-left py-1">{t('planetxLive.sample')}</th><th>n</th><th>p (ϖ)</th><th>p (Ω)</th><th>p (ω)</th>
                    </tr></thead>
                    <tbody className="font-mono text-gray-200">
                      <tr className="border-t border-white/5">
                        <td className="py-1 font-sans">{t('planetxLive.sampleComplete', { cc: data.selection.max_condition_code ?? 5 })}</td>
                        <td className="text-center">{data.varpi.n}</td><td className="text-center">{fmtP(data.varpi.p)}</td>
                        <td className="text-center">{fmtP(data.node.p)}</td><td className="text-center">{fmtP(data.argperi.p)}</td>
                      </tr>
                      <tr className="border-t border-white/5">
                        <td className="py-1 font-sans">{t('planetxLive.sampleLiterature')}</td>
                        <td className="text-center">{data.literature.n}</td><td className="text-center">{fmtP(data.literature.varpi.p)}</td>
                        <td className="text-center">{fmtP(data.literature.node.p)}</td><td className="text-center">{fmtP(data.literature.argperi.p)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p className="text-[11px] text-gray-400 mt-2">{t('planetxLive.compareNote')}</p>
              </div>
            )}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div>
                <div className="text-[11px] text-gray-400 mb-1">{t('planetxLive.periPlot')}</div>
                <div className="h-80">
                  <ResponsiveContainer width="100%" height="100%">
                    <ScatterChart margin={{ top: 10, right: 10, bottom: 20, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis type="number" dataKey="x" domain={[-lim, lim]} tick={{ fontSize: 10, fill: '#6b7280' }}
                        label={{ value: 'q·cos ϖ (AU)', position: 'insideBottom', offset: -10, fontSize: 10, fill: '#6b7280' }} />
                      <YAxis type="number" dataKey="y" domain={[-lim, lim]} tick={{ fontSize: 10, fill: '#6b7280' }} width={40} />
                      <ReferenceLine x={0} stroke="rgba(255,255,255,0.15)" />
                      <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" />
                      <ReferenceLine stroke="#a78bfa" strokeDasharray="4 3"
                        segment={[{ x: 0, y: 0 }, { x: lim * Math.cos((meanDir * Math.PI) / 180), y: lim * Math.sin((meanDir * Math.PI) / 180) }]} />
                      <Tooltip content={<TnoTooltip />} />
                      <Scatter data={peri} fill="#8b5cf6" isAnimationActive={false} />
                      <Scatter data={periLit} fill="#f59e0b" isAnimationActive={false} />
                    </ScatterChart>
                  </ResponsiveContainer>
                </div>
                <p className="text-[10px] text-gray-500">{t('planetxLive.periNote', { mean: meanDir })} {t('planetxLive.periLegend')}</p>
              </div>
              <div>
                <div className="text-[11px] text-gray-400 mb-1">{t('planetxLive.aqPlot')}</div>
                <div className="h-80">
                  <ResponsiveContainer width="100%" height="100%">
                    <ScatterChart margin={{ top: 10, right: 10, bottom: 20, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis type="number" dataKey="a" scale="log" domain={[100, 4000]} ticks={[150, 300, 600, 1200, 2500]}
                        tick={{ fontSize: 10, fill: '#6b7280' }}
                        label={{ value: 'a (AU, log)', position: 'insideBottom', offset: -10, fontSize: 10, fill: '#6b7280' }} />
                      <YAxis type="number" dataKey="q" domain={[25, 90]} tick={{ fontSize: 10, fill: '#6b7280' }} width={40}
                        label={{ value: 'q (AU)', angle: -90, position: 'insideLeft', fontSize: 10, fill: '#6b7280' }} />
                      <ReferenceLine y={30} stroke="#f59e0b" strokeDasharray="4 3" label={{ value: 'Neptune 30 AU', fill: '#f59e0b', fontSize: 10, position: 'insideBottomRight' }} />
                      <Tooltip content={<TnoTooltip />} />
                      <Scatter data={data.objects.filter((o) => o.in_sample).map((o) => ({ a: o.a_au, q: o.q_au, o }))} fill="#60a5fa" isAnimationActive={false} />
                      <Scatter data={data.objects.filter((o) => !o.in_sample).map((o) => ({ a: o.a_au, q: o.q_au, o }))} fill="#4b5563" isAnimationActive={false} />
                    </ScatterChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
            <div className="mt-4 p-3 rounded-lg bg-white/[0.02] border border-white/10 text-[11px] text-gray-400">
              <span className="text-amber-300 font-semibold">{t('planetxLive.caveatTitle')}</span> {t('planetxLive.caveat')}
            </div>
            <details className="mt-3">
              <summary className="text-xs text-sky-400 cursor-pointer">{t('planetxLive.table', { n: data.objects.length })}</summary>
              <div className="overflow-x-auto mt-2">
                <table className="w-full text-xs">
                  <thead className="text-gray-500 border-b border-white/5">
                    <tr><th className="text-left py-1">{t('catalogLive.object')}</th><th>a (AU)</th><th>q (AU)</th><th>e</th><th>i (°)</th><th>ϖ (°)</th><th>H</th><th title={t('planetxLive.ccHelp')}>CC</th><th>{t('planetxLive.litCol')}</th></tr>
                  </thead>
                  <tbody>
                    {data.objects.map((o) => (
                      <tr key={o.designation} className={`border-b border-white/[0.03] font-mono ${o.in_sample ? 'text-gray-300' : 'text-gray-600'}`}>
                        <td className="py-1 font-sans"><Link className="text-sky-300 hover:underline" to={`/catalog?q=${encodeURIComponent(o.designation)}`}>{o.name}</Link></td>
                        <td className="text-center">{o.a_au.toFixed(0)}</td><td className="text-center">{o.q_au.toFixed(1)}</td>
                        <td className="text-center">{o.e?.toFixed(3) ?? '—'}</td><td className="text-center">{o.i_deg?.toFixed(1) ?? '—'}</td>
                        <td className="text-center">{o.varpi_deg.toFixed(1)}</td><td className="text-center">{o.H ?? '—'}</td>
                        <td className="text-center">{o.condition_code ?? '—'}</td><td className="text-center">{o.in_literature ? '✓' : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
            <p className="text-[10px] text-gray-600 mt-2">{data.source}{data.missing ? ` · ${t('planetxLive.missing', { n: data.missing })}` : ''}</p>
          </>
        )}
      </div>

      {/* Can SPHEREx / OrbitScope find it? */}
      <div className={card}>
        <h2 className="text-lg font-semibold text-white mb-2 flex items-center gap-2"><Telescope className="w-5 h-5 text-sky-400" />{t('planetxLive.spherexTitle')}</h2>
        <p className="text-sm text-gray-400 leading-relaxed">{t('planetxLive.spherexText')}</p>
        <Link to="/detection" className="inline-block mt-3 text-xs text-sky-400 hover:underline">{t('nav.detection')} →</Link>
      </div>

      {/* Literature evidence */}
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">{t('planetx.evidence.title')}</h2>
        <p className="text-[11px] text-gray-500 mb-3">{t('planetxLive.literature')}</p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {EVIDENCE.map((ev) => (
            <div key={ev.key} className="rounded-xl border border-white/5 bg-white/[0.02] p-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-white">{t(`planetx.evidence.${ev.key}.title`)}</h3>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border ${STRENGTH_COLORS[ev.strength]}`}>{t(`planetxLive.strength.${ev.strength}`)}</span>
              </div>
              <p className="text-xs text-gray-400 leading-relaxed">{t(`planetx.evidence.${ev.key}.description`)}</p>
              <div className="mt-3 text-[10px] text-gray-600">{ev.year}</div>
            </div>
          ))}
        </div>
      </div>

      <div className={card}>
        <h2 className="text-lg font-semibold text-white mb-1">{t('planetx.predictions.title')}</h2>
        <p className="text-[11px] text-gray-500 mb-3">{t('planetxLive.predSource')}</p>
        <table className="w-full text-xs">
          <tbody>
            {PREDICTIONS.map((p) => (
              <tr key={p.key} className="border-b border-white/[0.03]">
                <td className="py-2 text-gray-300">{t(`planetxLive.pred.${p.key}`)}</td>
                <td className="py-2 font-mono text-blue-300">{p.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className={card}>
        <h2 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2"><BookOpen className="w-4 h-4" /> {t('planetx.references.title')}</h2>
        <ul className="space-y-2 text-xs text-gray-400">
          <li>Batygin, K. & Brown, M. E. (2016). Evidence for a Distant Giant Planet in the Solar System. <i>AJ</i> 151, 22. <a href="https://doi.org/10.3847/0004-6256/151/2/22" target="_blank" rel="noopener" className="text-blue-400 hover:underline">DOI</a></li>
          <li>Brown, M. E. & Batygin, K. (2021). The Orbit of Planet Nine. <i>AJ</i> 162, 219. <a href="https://doi.org/10.3847/1538-3881/ac2056" target="_blank" rel="noopener" className="text-blue-400 hover:underline">DOI</a></li>
          <li>Trujillo, C. A. & Sheppard, S. S. (2014). A Sedna-like body with a perihelion of 80 AU. <i>Nature</i> 507, 471. <a href="https://doi.org/10.1038/nature13156" target="_blank" rel="noopener" className="text-blue-400 hover:underline">DOI</a></li>
          <li>Batygin, K. et al. (2019). The planet nine hypothesis. <i>Physics Reports</i> 805, 1–53. <a href="https://doi.org/10.1016/j.physrep.2019.01.009" target="_blank" rel="noopener" className="text-blue-400 hover:underline">DOI</a></li>
          <li>Shankman, C. et al. (2017). OSSOS VI. Striking Biases in the Detection of Large Semimajor Axis Trans-Neptunian Objects. <i>AJ</i> 154, 50. <a href="https://doi.org/10.3847/1538-3881/aa7aed" target="_blank" rel="noopener" className="text-blue-400 hover:underline">DOI</a></li>
          <li>Napier, K. J. et al. (2021). No Evidence for Orbital Clustering in the Extreme Trans-Neptunian Objects. <i>PSJ</i> 2, 59. <a href="https://doi.org/10.3847/PSJ/abe53e" target="_blank" rel="noopener" className="text-blue-400 hover:underline">DOI</a></li>
        </ul>
      </div>
    </div>
  );
}
