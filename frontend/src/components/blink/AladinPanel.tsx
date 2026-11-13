import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, ExternalLink, Globe2, WifiOff } from 'lucide-react';
import { useNetwork } from '../../lib/network';

/**
 * Sky context from CDS Aladin Lite (loaded on demand, only when the panel is opened).
 * Shows optical / near-IR / mid-IR all-sky surveys around the target, with the SPHEREx cutout
 * footprint and the target marked. Needs WebGL2; if the library or CDS cannot be reached the panel
 * says so and links to the Aladin web page.
 */

// Pinned release from npm (the ES-module build exports the `A` API as default).
const ALADIN_SRC = 'https://cdn.jsdelivr.net/npm/aladin-lite@3.8.2/dist/aladin.js';
// HiPS served by NASA/IPAC IRSA (mirrors of the CDS surveys), so the panel works even when CDS is unreachable.
const HIPS = 'https://irsa.ipac.caltech.edu/data/hips/CDS';
const SURVEYS = [
  { id: `${HIPS}/DSS2/color`, label: 'DSS2 (optical)' },
  { id: `${HIPS}/2MASS/Color`, label: '2MASS (1.2–2.2 µm)' },
  { id: `${HIPS}/AllWISE/W2`, label: 'AllWISE W2 (4.6 µm)' },
];

/* Minimal typing of the parts of the Aladin Lite v3 API used here. */
interface AladinInstance {
  setImageSurvey: (id: string) => void;
  addOverlay: (o: unknown) => void;
  addCatalog: (c: unknown) => void;
  gotoRaDec: (ra: number, dec: number) => void;
  setFoV: (deg: number) => void;
}
interface AladinGlobal {
  init: Promise<void>;
  aladin: (el: HTMLElement, opts: Record<string, unknown>) => AladinInstance;
  graphicOverlay: (opts: Record<string, unknown>) => { add: (shape: unknown) => void };
  polygon: (pts: [number, number][], opts?: Record<string, unknown>) => unknown;
  catalog: (opts: Record<string, unknown>) => { addSources: (s: unknown[]) => void };
  marker: (ra: number, dec: number, opts: Record<string, unknown>) => unknown;
}
let loader: Promise<AladinGlobal> | null = null;
function loadAladin(): Promise<AladinGlobal> {
  if (!loader) {
    loader = import(/* @vite-ignore */ ALADIN_SRC)
      .then((m: { default?: AladinGlobal }) => {
        if (!m.default) throw new Error('Aladin Lite did not initialise');
        return m.default;
      })
      .catch((e) => { loader = null; throw e; });
  }
  return loader;
}

/** Corners of the north-up TAN cutout (small-field approximation is fine at <= 0.5 deg). */
function footprint(ra: number, dec: number, fovDeg: number): [number, number][] {
  const h = fovDeg / 2;
  const c = Math.cos((dec * Math.PI) / 180) || 1e-6;
  return [[ra + h / c, dec - h], [ra - h / c, dec - h], [ra - h / c, dec + h], [ra + h / c, dec + h]];
}

export default function AladinPanel({ ra, dec, fov, label }: { ra: number; dec: number; fov: number; label: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [survey, setSurvey] = useState(SURVEYS[1].id);
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const box = useRef<HTMLDivElement>(null);
  const viewer = useRef<AladinInstance | null>(null);
  // Aladin Lite and its sky surveys come from the internet: without it (offline Pi demo) say so.
  const offline = useNetwork().online === false;

  useEffect(() => {
    if (!open || offline || !box.current) return;
    let cancelled = false;
    setState('loading');
    loadAladin()
      .then(async (A) => {
        await A.init;
        if (cancelled || !box.current) return;
        box.current.innerHTML = '';
        const al = A.aladin(box.current, {
          survey, fov: Math.max(fov * 2.5, 0.15), target: `${ra} ${dec}`,
          showReticle: false, showLayersControl: true, showGotoControl: false, showFullscreenControl: true,
          showFrame: false, showCooGridControl: true, log: false,
          // only our IRSA-hosted surveys in the layer menu (the default list needs the CDS MocServer)
          hipsList: SURVEYS.map((s) => ({ id: s.id, name: s.label, url: s.id })),
        });
        const ov = A.graphicOverlay({ color: '#38bdf8', lineWidth: 2 });
        al.addOverlay(ov);
        ov.add(A.polygon(footprint(ra, dec, fov)));
        const cat = A.catalog({ name: 'target', color: '#f472b6', sourceSize: 14, shape: 'cross' });
        al.addCatalog(cat);
        cat.addSources([A.marker(ra, dec, { popupTitle: label, popupDesc: `${ra.toFixed(5)}°, ${dec.toFixed(5)}°` })]);
        viewer.current = al;
        setState('ready');
      })
      .catch(() => { if (!cancelled) setState('error'); });
    return () => { cancelled = true; viewer.current = null; };
    // re-create only when the field changes; the survey is switched in place below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, offline, ra, dec, fov, label]);

  useEffect(() => { viewer.current?.setImageSurvey(survey); }, [survey]);

  const aladinUrl = `https://aladin.cds.unistra.fr/AladinLite/?target=${encodeURIComponent(`${ra} ${dec}`)}&fov=${Math.max(fov * 2.5, 0.15)}`;

  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4">
      <button type="button" onClick={() => setOpen((o) => !o)} className="w-full flex items-center justify-between text-left">
        <span className="flex items-center gap-2 text-sm font-semibold text-white">
          <Globe2 className="w-4 h-4 text-sky-400" /> {t('blink.aladin.title')}
        </span>
        {open ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
      </button>
      {open && offline && (
        <p className="mt-3 text-[11px] text-amber-300 flex items-center gap-1.5">
          <WifiOff className="w-3.5 h-3.5" /> {t('pi.aladinOffline')}
        </p>
      )}
      {open && !offline && (
        <div className="mt-3 space-y-2">
          <p className="text-[11px] text-gray-500">{t('blink.aladin.intro')}</p>
          <div className="flex flex-wrap items-center gap-2">
            {SURVEYS.map((s) => (
              <button key={s.id} type="button" onClick={() => setSurvey(s.id)}
                className={`px-2 py-1 rounded-lg text-[11px] border ${survey === s.id ? 'bg-sky-500/15 border-sky-500/30 text-sky-200' : 'bg-white/5 border-white/10 text-gray-300'}`}>
                {s.label}
              </button>
            ))}
            <a href={aladinUrl} target="_blank" rel="noreferrer" className="ml-auto text-[11px] text-sky-300 flex items-center gap-1 hover:underline">
              Aladin <ExternalLink className="w-3 h-3" />
            </a>
          </div>
          <div ref={box} className="w-full h-[380px] rounded-lg overflow-hidden bg-black/40" />
          {state === 'loading' && <p className="text-[11px] text-gray-500">{t('blink.aladin.loading')}</p>}
          {state === 'error' && <p className="text-[11px] text-amber-300">{t('blink.aladin.error')}</p>}
          <p className="text-[10px] text-gray-600">{t('blink.aladin.credit')}</p>
        </div>
      )}
    </div>
  );
}
