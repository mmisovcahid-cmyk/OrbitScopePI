import { useTranslation } from 'react-i18next';
import { WifiOff } from 'lucide-react';
import { formatSnapshot, useNetwork } from '../../lib/network';

/** Shown on every page while the backend has no internet: only cached real data is available. */
export default function OfflineBanner() {
  const { t } = useTranslation();
  const { online } = useNetwork();
  if (online !== false) return null;
  return (
    <div role="status" className="flex items-center gap-2 px-4 py-2 text-xs bg-amber-500/10 border-b border-amber-500/30 text-amber-200">
      <WifiOff className="w-4 h-4 shrink-0" />
      <span><strong>{t('pi.offlineTitle')}</strong> {t('pi.offlineBody')}</span>
    </div>
  );
}

/** Small label under a result that came from an offline snapshot (backend `offline_snapshot`). */
export function SnapshotNote({ snapshot }: { snapshot?: { saved_at: string } | null }) {
  const { t, i18n } = useTranslation();
  if (!snapshot?.saved_at) return null;
  const when = formatSnapshot(snapshot.saved_at, i18n.language);
  return (
    <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-amber-300/90">
      <WifiOff className="w-3 h-3" /> {t('pi.snapshot', { when })}
    </p>
  );
}
