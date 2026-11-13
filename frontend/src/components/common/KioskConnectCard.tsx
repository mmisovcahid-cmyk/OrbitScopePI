import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Smartphone, Wifi, X } from 'lucide-react';
import QRCode from 'qrcode';
import { systemService } from '../../services';

/**
 * Kiosk screen only: two QR codes in a corner so visitors can follow on their phones.
 * 1) join the Pi's Wi-Fi access point (the password is only sent to the Pi itself),
 * 2) open the site. Data comes from /system/kiosk (values written by deploy/pi/install.sh).
 */
interface KioskInfo {
  public_url: string | null;
  wifi: { ssid: string; security: string; password?: string } | null;
}

// Wi-Fi QR payload (understood by Android and iOS cameras); \ ; , : " must be escaped.
const esc = (s: string) => s.replace(/([\\;,:"])/g, '\\$1');

function useQr(text: string | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!text) { setUrl(null); return; }
    let alive = true;
    QRCode.toDataURL(text, { margin: 1, width: 240, color: { dark: '#000000', light: '#ffffff' } })
      .then((u) => { if (alive) setUrl(u); })
      .catch(() => { if (alive) setUrl(null); });
    return () => { alive = false; };
  }, [text]);
  return url;
}

export default function KioskConnectCard() {
  const { t } = useTranslation();
  const [info, setInfo] = useState<KioskInfo | null>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    systemService.kiosk().then((r) => setInfo(r.data?.data ?? null)).catch(() => setInfo(null));
  }, []);

  const wifi = info?.wifi;
  const wifiText = wifi
    ? `WIFI:T:${wifi.password ? 'WPA' : 'nopass'};S:${esc(wifi.ssid)};${wifi.password ? `P:${esc(wifi.password)};` : ''};`
    : null;
  const siteUrl = info?.public_url ?? null;
  const wifiQr = useQr(wifiText);
  const siteQr = useQr(siteUrl);

  if (hidden || (!wifiQr && !siteQr)) return null;
  return (
    <div className="fixed bottom-3 right-3 z-[60] flex gap-3 items-end rounded-2xl bg-[#070b18]/95 border border-white/15 p-3 shadow-2xl">
      {wifiQr && wifi && (
        <figure className="text-center">
          <img src={wifiQr} alt="" className="w-28 h-28 rounded-md" />
          <figcaption className="mt-1 text-[11px] text-gray-300 flex items-center justify-center gap-1">
            <Wifi className="w-3 h-3 text-sky-400" /> {t('pi.qrWifi')}
          </figcaption>
          <div className="text-[11px] font-mono text-sky-300">{wifi.ssid}</div>
        </figure>
      )}
      {siteQr && siteUrl && (
        <figure className="text-center">
          <img src={siteQr} alt="" className="w-28 h-28 rounded-md" />
          <figcaption className="mt-1 text-[11px] text-gray-300 flex items-center justify-center gap-1">
            <Smartphone className="w-3 h-3 text-sky-400" /> {t('pi.qrSite')}
          </figcaption>
          <div className="text-[11px] font-mono text-sky-300">{siteUrl.replace(/^https?:\/\//, '')}</div>
        </figure>
      )}
      <button onClick={() => setHidden(true)} aria-label={t('pi.hideQr')}
        className="self-start p-1 rounded-md text-gray-400 hover:text-white hover:bg-white/10">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
