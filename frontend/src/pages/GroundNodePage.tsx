import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Camera, Upload, RadioTower, Telescope, Crosshair, Eye, Loader2, AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';
import { groundService } from '../services';
import api from '../services/api';
import { errorText } from '../lib/spherex';

/**
 * Ground Node: the Raspberry Pi as a sensor-agnostic observing station.
 * Any source (Pi camera, an uploaded image sequence, later a telescope via INDI) goes through the
 * same chain: trails -> plate solve -> same sky direction in SPHEREx. Provenance is always shown.
 */
interface Trail {
  frame: number; x0: number; y0: number; x1: number; y1: number; length_px: number; angle_deg: number;
  peak_sigma: number; dashed?: boolean; sky?: { ra0: number; dec0: number; ra1: number; dec1: number };
}
interface Solve { status: string; reason?: string; ra?: number; dec?: number; field_width_deg?: number; solver?: string }
interface Frame { file: string; time_utc: string | null; time_local: string | null; time_note: string | null; lat: number | null; lon: number | null; camera: string | null; exposure_s: number | null; original_name?: string }
interface Session {
  id: string; source: string; label: string; provenance?: string; status: string; frames: Frame[];
  analysis: null | { frames: number; size_px: [number, number]; trails: Trail[]; n_trails: number; n_dashed: number;
    plate_solve: Solve; satellite_id: { status: string; reason: string | null }; elapsed_s: number };
}
interface Summary { id: string; label: string; source: string; n_frames: number; n_trails: number | null; solved: boolean; status: string }
interface Status { camera: boolean; plate_solver: boolean; inputs: Record<string, boolean> }

const card = 'rounded-xl border border-white/5 bg-white/[0.02] p-4';

function Chip({ ok, label }: { ok: boolean | null; label: string }) {
  const Icon = ok ? CheckCircle2 : XCircle;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs border ${ok ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200' : 'border-white/10 bg-white/5 text-gray-400'}`}>
      <Icon className="w-3.5 h-3.5" /> {label}
    </span>
  );
}

export default function GroundNodePage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status | null>(null);
  const [list, setList] = useState<Summary[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [files, setFiles] = useState<FileList | null>(null);
  const [label, setLabel] = useState('');
  const [nFrames, setNFrames] = useState(5);
  const [expo, setExpo] = useState(2);
  const [idx, setIdx] = useState(0);

  const refresh = useCallback(async () => {
    const [s, l] = await Promise.all([groundService.status(), groundService.sessions()]);
    setStatus(s.data?.data ?? null);
    setList(l.data?.data ?? []);
  }, []);
  useEffect(() => { refresh().catch((e) => setError(errorText(e, t('errors.timeout')))); }, [refresh, t]);

  const open = useCallback(async (id: string) => {
    setError(null);
    const r = await groundService.session(id);
    setSession(r.data?.data ?? null);
    setIdx(0);
  }, []);

  const run = async (what: string, fn: () => Promise<string>) => {
    setBusy(what); setError(null);
    try {
      const id = await fn();
      setBusy('analyze');
      const a = await groundService.analyze(id);
      setSession(a.data?.data ?? null);
      setIdx(0);
      await refresh();
    } catch (e) {
      setError(errorText(e, t('errors.timeout')));
    } finally {
      setBusy(null);
    }
  };

  const upload = () => {
    if (!files?.length) { setError(t('ground.pickFiles')); return; }
    return run('upload', async () => {
      const r = await groundService.upload(Array.from(files), label);
      return r.data.data.id as string;
    });
  };
  const capture = () => run('capture', async () => (await groundService.capture(nFrames, expo)).data.data.id as string);

  const a = session?.analysis;
  const frameTrails = useMemo(() => (a ? a.trails.filter((tr) => tr.frame === idx) : []), [a, idx]);
  const frameIdxWithTrails = useMemo(() => Array.from(new Set(a?.trails.map((tr) => tr.frame) ?? [])), [a]);
  const solve = a?.plate_solve;
  const f = session?.frames[idx];

  return (
    <div className="space-y-6 p-4 md:p-6 max-w-6xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2"><RadioTower className="w-6 h-6 text-sky-400" />{t('ground.title')}</h1>
        <p className="text-sm text-gray-400 mt-1 max-w-3xl">{t('ground.intro')}</p>
        <div className="flex flex-wrap gap-2 mt-3">
          <Chip ok={status?.camera ?? null} label={t('ground.inCamera')} />
          <Chip ok label={t('ground.inUpload')} />
          <Chip ok={false} label={t('ground.inIndi')} />
          <Chip ok={status?.plate_solver ?? null} label={t('ground.solver')} />
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className={card}>
          <h2 className="text-sm font-semibold text-white flex items-center gap-2"><Upload className="w-4 h-4 text-sky-400" />{t('ground.uploadTitle')}</h2>
          <p className="text-[11px] text-gray-500 mt-1">{t('ground.uploadHint')}</p>
          <input type="file" multiple accept=".jpg,.jpeg,.png,.tif,.tiff,.fits,.fit,.fts" onChange={(e) => setFiles(e.target.files)}
            className="mt-3 block w-full text-xs text-gray-300 file:mr-3 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-white/10 file:text-gray-200" />
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t('ground.labelPh')}
            className="mt-2 w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white" />
          <button onClick={upload} disabled={!!busy} className="mt-3 w-full py-2 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-sm font-semibold text-white">
            {busy === 'upload' ? t('ground.uploading') : t('ground.uploadBtn')}
          </button>
        </div>

        <div className={card}>
          <h2 className="text-sm font-semibold text-white flex items-center gap-2"><Camera className="w-4 h-4 text-sky-400" />{t('ground.cameraTitle')}</h2>
          <p className="text-[11px] text-gray-500 mt-1">{t('ground.cameraHint')}</p>
          <div className="grid grid-cols-2 gap-2 mt-3">
            <label className="text-[11px] text-gray-400">{t('ground.nFrames')}
              <input type="number" min={3} max={60} value={nFrames} onChange={(e) => setNFrames(Number(e.target.value))}
                className="mt-1 w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white" /></label>
            <label className="text-[11px] text-gray-400">{t('ground.exposure')}
              <input type="number" min={0.01} max={60} step={0.5} value={expo} onChange={(e) => setExpo(Number(e.target.value))}
                className="mt-1 w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white" /></label>
          </div>
          <button onClick={capture} disabled={!!busy || !status?.camera} className="mt-3 w-full py-2 rounded-lg bg-white/10 hover:bg-white/15 disabled:opacity-40 text-sm font-semibold text-white">
            {busy === 'capture' ? t('ground.capturing') : status?.camera ? t('ground.captureBtn') : t('ground.noCamera')}
          </button>
          <p className="text-[11px] text-gray-500 mt-3 flex items-start gap-1.5"><Telescope className="w-3.5 h-3.5 shrink-0 mt-0.5" />{t('ground.indiNote')}</p>
        </div>
      </div>

      {busy && <p className="text-sm text-sky-300 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />{t(`ground.busy.${busy}`)}</p>}
      {error && <p className="text-sm text-amber-300 flex items-center gap-2"><AlertTriangle className="w-4 h-4" />{error}</p>}

      <div className="grid md:grid-cols-[16rem_1fr] gap-4">
        <div className={`${card} space-y-1.5 max-h-[32rem] overflow-y-auto`}>
          <h2 className="text-sm font-semibold text-white mb-2">{t('ground.sessions')}</h2>
          {list.length === 0 && <p className="text-xs text-gray-500">{t('ground.noSessions')}</p>}
          {list.map((s) => (
            <button key={s.id} onClick={() => open(s.id)}
              className={`w-full text-left px-3 py-2 rounded-lg text-xs border ${session?.id === s.id ? 'border-sky-500/40 bg-sky-500/10' : 'border-white/5 hover:bg-white/5'}`}>
              <div className="text-gray-200 truncate">{s.label}</div>
              <div className="text-gray-500 mt-0.5">{t(`ground.src.${s.source}`)} · {s.n_frames} {t('ground.framesShort')}{s.n_trails != null ? ` · ${s.n_trails} ${t('ground.trailsShort')}` : ''}</div>
            </button>
          ))}
        </div>

        {session ? (
          <div className={`${card} space-y-4`}>
            <div>
              <h2 className="text-base font-semibold text-white">{session.label}</h2>
              <p className="text-xs text-gray-400 mt-0.5">{session.provenance ?? t(`ground.src.${session.source}`)}</p>
            </div>

            {a && (
              <div className="grid sm:grid-cols-3 gap-3 text-xs">
                <div className="rounded-lg bg-white/[0.03] p-3"><div className="text-gray-400">{t('ground.trails')}</div>
                  <div className="text-xl font-bold text-white">{a.n_trails}</div>
                  {a.n_dashed > 0 && <div className="text-gray-500">{t('ground.dashed', { n: a.n_dashed })}</div>}</div>
                <div className="rounded-lg bg-white/[0.03] p-3"><div className="text-gray-400">{t('ground.solver')}</div>
                  {solve?.status === 'solved'
                    ? <div className="text-white font-mono">RA {solve.ra?.toFixed(2)}° Dec {solve.dec?.toFixed(2)}°<div className="text-gray-500 font-sans">{t('ground.fov', { w: solve.field_width_deg })}</div></div>
                    : <div className="text-amber-300">{solve?.reason}</div>}</div>
                <div className="rounded-lg bg-white/[0.03] p-3"><div className="text-gray-400">{t('ground.satId')}</div>
                  <div className="text-gray-300">{a.satellite_id.status === 'unavailable' ? a.satellite_id.reason : t('ground.satPending')}</div></div>
              </div>
            )}

            {solve?.status === 'solved' && (
              <Link to={`/?ra=${solve.ra}&dec=${solve.dec}&fov=0.3`}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-500/15 border border-sky-500/30 text-xs text-sky-200">
                <Eye className="w-4 h-4" /> {t('ground.toSpherex')}
              </Link>
            )}

            {session.frames.length > 0 && (
              <div>
                <div className="relative w-full bg-black rounded-lg overflow-hidden">
                  <img src={`${api.defaults.baseURL}/api/v1/ground/sessions/${session.id}/frames/${idx}.jpg`} alt="" className="w-full h-auto block" />
                  {a && (
                    <svg className="absolute inset-0 w-full h-full" viewBox={`0 0 ${a.size_px[0]} ${a.size_px[1]}`} preserveAspectRatio="none">
                      {frameTrails.map((tr, i) => (
                        <line key={i} x1={tr.x0} y1={tr.y0} x2={tr.x1} y2={tr.y1} stroke={tr.dashed ? '#fbbf24' : '#38bdf8'} strokeWidth={Math.max(2, a.size_px[0] / 400)} strokeOpacity={0.85} />
                      ))}
                    </svg>
                  )}
                </div>
                <input type="range" min={0} max={session.frames.length - 1} value={idx} onChange={(e) => setIdx(Number(e.target.value))} className="w-full mt-2" />
                <div className="flex flex-wrap justify-between gap-2 text-[11px] text-gray-400">
                  <span>{t('ground.frame')} {idx + 1}/{session.frames.length}{f?.original_name ? ` · ${f.original_name}` : ''}</span>
                  <span className="font-mono">{f?.time_utc ? `${f.time_utc} UTC` : f?.time_local ? `${f.time_local} (${t('ground.noTz')})` : t('ground.noTime')}{f?.exposure_s ? ` · ${f.exposure_s} s` : ''}{f?.lat != null ? ` · ${f.lat.toFixed(3)}, ${f.lon?.toFixed(3)}` : ''}</span>
                </div>
                {frameIdxWithTrails.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2 items-center text-[11px] text-gray-400">
                    <Crosshair className="w-3.5 h-3.5" />{t('ground.framesWithTrails')}
                    {frameIdxWithTrails.map((n) => (
                      <button key={n} onClick={() => setIdx(n)} className={`px-2 py-0.5 rounded ${n === idx ? 'bg-sky-500/30 text-sky-100' : 'bg-white/5'}`}>{n + 1}</button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {a && a.trails.length > 0 && (
              <table className="w-full text-xs">
                <thead><tr className="text-gray-500 text-left"><th className="py-1">{t('ground.frame')}</th><th>{t('ground.length')}</th><th>{t('ground.angle')}</th><th>{t('ground.kind')}</th><th>RA/Dec</th></tr></thead>
                <tbody>
                  {a.trails.map((tr, i) => (
                    <tr key={i} className="border-t border-white/5 text-gray-300">
                      <td className="py-1">{tr.frame + 1}</td><td>{tr.length_px} px</td><td>{tr.angle_deg}°</td>
                      <td>{tr.dashed ? t('ground.kindPlane') : t('ground.kindUnknown')}</td>
                      <td className="font-mono">{tr.sky ? `${tr.sky.ra0}, ${tr.sky.dec0} → ${tr.sky.ra1}, ${tr.sky.dec1}` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="text-[11px] text-gray-500">{t('ground.honesty')}</p>
          </div>
        ) : (
          <div className={`${card} text-sm text-gray-500`}>{t('ground.pickSession')}</div>
        )}
      </div>
    </div>
  );
}
