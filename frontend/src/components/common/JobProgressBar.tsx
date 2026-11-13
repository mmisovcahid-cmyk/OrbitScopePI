import { useTranslation } from 'react-i18next';
import { Loader2, X } from 'lucide-react';
import { JobProgress } from '../../lib/jobs';

interface Props {
  progress: JobProgress | null;
  onCancel?: () => void;
  hint?: string;
}

/** Stage, counter and bar for a running background job. */
export default function JobProgressBar({ progress, onCancel, hint }: Props) {
  const { t } = useTranslation();
  const stage = progress?.stage ?? 'queued';
  const pct = progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : null;
  return (
    <div className="py-6 px-2 flex flex-col items-center gap-3" role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-sm text-gray-200">
        <Loader2 className="w-4 h-4 animate-spin text-sky-400" />
        <span>{t(`jobs.stage.${stage}`, { defaultValue: stage })}</span>
        {progress && progress.total > 0 && <span className="text-gray-400 font-mono">{progress.done}/{progress.total}</span>}
        <span className="text-gray-500 font-mono">· {Math.round(progress?.elapsed_s ?? 0)} s</span>
      </div>
      <div className="w-full max-w-md h-1.5 rounded-full bg-white/10 overflow-hidden">
        <div
          className={`h-full bg-sky-400 transition-all duration-500 ${pct === null ? 'w-1/3 animate-pulse' : ''}`}
          style={pct !== null ? { width: `${Math.max(4, pct)}%` } : undefined}
        />
      </div>
      {progress?.status === 'queued' && (progress.queued_s ?? 0) > 1 && (
        <p className="text-[11px] text-amber-300">{t('jobs.queued')}</p>
      )}
      {hint && <p className="text-[11px] text-gray-500 text-center max-w-lg">{hint}</p>}
      {onCancel && (
        <button onClick={onCancel} className="text-[11px] text-gray-400 hover:text-red-300 flex items-center gap-1">
          <X className="w-3.5 h-3.5" /> {t('jobs.cancel')}
        </button>
      )}
    </div>
  );
}
