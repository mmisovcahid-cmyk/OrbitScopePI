import { useEffect, useMemo, useRef, useState } from 'react';

export interface SkyMarker {
  id: string;
  ra: number;
  dec: number;
  color: string;
  shape: 'star' | 'circle' | 'square';
  label?: string;
  size?: number;
}

interface Props {
  markers: SkyMarker[];
  selectedId?: string | null;
  onSelect?: (m: SkyMarker) => void;
  height?: number;
}

const D2R = Math.PI / 180;
const OBLIQUITY = 23.4392911 * D2R;

/** Hammer-Aitoff projection; RA increases to the left (sky as seen from inside). Returns [-1..1] coords. */
function project(ra: number, dec: number): [number, number] {
  let l = (180 - ra) * D2R; // centre at RA = 12h
  if (l > Math.PI) l -= 2 * Math.PI;
  if (l < -Math.PI) l += 2 * Math.PI;
  const b = dec * D2R;
  const z = Math.sqrt(1 + Math.cos(b) * Math.cos(l / 2));
  const x = (2 * Math.SQRT2 * Math.cos(b) * Math.sin(l / 2)) / z;
  const y = (Math.SQRT2 * Math.sin(b)) / z;
  return [x / (2 * Math.SQRT2), y / Math.SQRT2];
}

function eclipticToEq(lambdaDeg: number): [number, number] {
  const l = lambdaDeg * D2R;
  const dec = Math.asin(Math.sin(OBLIQUITY) * Math.sin(l));
  const ra = Math.atan2(Math.cos(OBLIQUITY) * Math.sin(l), Math.cos(l));
  return [((ra / D2R) + 360) % 360, dec / D2R];
}

function galacticToEq(lDeg: number): [number, number] {
  // IAU J2000 galactic pole / origin
  const aNGP = 192.85948 * D2R, dNGP = 27.12825 * D2R, lNCP = 122.93192 * D2R;
  const l = lDeg * D2R, b = 0;
  const sinD = Math.sin(b) * Math.sin(dNGP) + Math.cos(b) * Math.cos(dNGP) * Math.cos(lNCP - l);
  const dec = Math.asin(sinD);
  const ra = aNGP + Math.atan2(Math.cos(b) * Math.sin(lNCP - l), Math.sin(b) * Math.cos(dNGP) - Math.cos(b) * Math.sin(dNGP) * Math.cos(lNCP - l));
  return [((ra / D2R) % 360 + 360) % 360, dec / D2R];
}

/** All-sky map with the real ecliptic and galactic plane, clickable markers. */
export default function AllSkyMap({ markers, selectedId, onSelect, height = 360 }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [hover, setHover] = useState<SkyMarker | null>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const h = Math.min(height, Math.round(width / 2));
  const toPx = useMemo(() => (ra: number, dec: number): [number, number] => {
    const [x, y] = project(ra, dec);
    return [width / 2 + x * (width / 2 - 8), h / 2 - y * (h / 2 - 8)];
  }, [width, h]);

  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = width * dpr; c.height = h * dpr;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, h);

    // Sky ellipse
    ctx.beginPath();
    ctx.ellipse(width / 2, h / 2, width / 2 - 8, h / 2 - 8, 0, 0, Math.PI * 2);
    ctx.fillStyle = '#070d1d';
    ctx.fill();
    ctx.strokeStyle = 'rgba(148,163,184,0.25)';
    ctx.stroke();

    const line = (pts: [number, number][], color: string, dash: number[] = []) => {
      ctx.beginPath();
      ctx.setLineDash(dash);
      let prev: [number, number] | null = null;
      for (const [ra, dec] of pts) {
        const p = toPx(ra, dec);
        if (prev && Math.abs(p[0] - prev[0]) > width / 3) ctx.moveTo(p[0], p[1]); // wrap at RA 0h
        else if (prev) ctx.lineTo(p[0], p[1]);
        else ctx.moveTo(p[0], p[1]);
        prev = p;
      }
      ctx.strokeStyle = color;
      ctx.stroke();
      ctx.setLineDash([]);
    };
    // RA / Dec grid
    ctx.lineWidth = 0.6;
    for (let dec = -60; dec <= 60; dec += 30) line(Array.from({ length: 181 }, (_, i) => [i * 2, dec] as [number, number]), 'rgba(148,163,184,0.12)');
    for (let ra = 0; ra < 360; ra += 30) line(Array.from({ length: 91 }, (_, i) => [ra, -90 + i * 2] as [number, number]), 'rgba(148,163,184,0.12)');
    // Ecliptic (asteroids) and galactic plane (dense star fields)
    ctx.lineWidth = 1.2;
    line(Array.from({ length: 361 }, (_, i) => eclipticToEq(i)), 'rgba(250,204,21,0.55)', [6, 4]);
    line(Array.from({ length: 361 }, (_, i) => galacticToEq(i)), 'rgba(167,139,250,0.45)', [2, 3]);
    // RA labels
    ctx.fillStyle = 'rgba(148,163,184,0.6)';
    ctx.font = '10px sans-serif';
    for (const ra of [0, 6, 12, 18]) {
      const [x, y] = toPx(ra * 15 + 0.01, 0);
      ctx.fillText(`${ra}h`, x + 3, y - 3);
    }

    // Markers
    for (const m of markers) {
      const [x, y] = toPx(m.ra, m.dec);
      const s = (m.size ?? 4) * (m.id === selectedId ? 1.6 : 1);
      ctx.fillStyle = m.color;
      ctx.strokeStyle = m.id === selectedId ? '#ffffff' : 'rgba(0,0,0,0.6)';
      ctx.lineWidth = m.id === selectedId ? 1.5 : 0.8;
      ctx.beginPath();
      if (m.shape === 'square') ctx.rect(x - s, y - s, 2 * s, 2 * s);
      else if (m.shape === 'star') {
        for (let k = 0; k < 10; k++) {
          const r = k % 2 === 0 ? s * 1.5 : s * 0.6;
          const a = (k * Math.PI) / 5 - Math.PI / 2;
          if (k === 0) ctx.moveTo(x + r * Math.cos(a), y + r * Math.sin(a)); else ctx.lineTo(x + r * Math.cos(a), y + r * Math.sin(a));
        }
        ctx.closePath();
      } else ctx.arc(x, y, s, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      if (m.label && (m.shape === 'star' || m.id === selectedId)) {
        ctx.fillStyle = 'rgba(226,232,240,0.9)';
        ctx.fillText(m.label, x + s + 4, y + 3);
      }
    }
  }, [markers, selectedId, toPx, width, h]);

  const nearest = (e: React.MouseEvent): SkyMarker | null => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return null;
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    let best: SkyMarker | null = null, bd = 12;
    for (const m of markers) {
      const [x, y] = toPx(m.ra, m.dec);
      const d = Math.hypot(x - mx, y - my);
      if (d < bd) { bd = d; best = m; }
    }
    return best;
  };

  return (
    <div ref={boxRef} className="relative w-full">
      <canvas
        ref={ref}
        style={{ width, height: h, cursor: hover ? 'pointer' : 'default' }}
        onMouseMove={(e) => setHover(nearest(e))}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => { const m = nearest(e); if (m) onSelect?.(m); }}
      />
      {hover?.label && (
        <div className="absolute top-2 left-2 px-2 py-1 rounded bg-black/70 text-[11px] text-white pointer-events-none">{hover.label}</div>
      )}
    </div>
  );
}
