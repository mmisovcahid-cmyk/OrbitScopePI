import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import BlinkViewer from '../components/blink/BlinkViewer';
import JobProgressBar from '../components/common/JobProgressBar';
import api from '../services/api';
import { BlinkResult, apiParams, errorText, queryFromParams, queryToParams } from '../lib/spherex';
import { JobProgress, isAbort, runJob } from '../lib/jobs';

/** Minimal, iframe-friendly blink player: /embed?target=...&fov=...&det=... */
export default function EmbedPage() {
  const { t, i18n } = useTranslation();
  const [params] = useSearchParams();
  const query = useMemo(() => queryFromParams(params), [params]);
  const [result, setResult] = useState<BlinkResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);

  useEffect(() => {
    const lang = params.get('lang');
    if (lang === 'az' || lang === 'en') i18n.changeLanguage(lang);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!query) { setError(t('blink.errors.empty')); return; }
    const ctrl = new AbortController();
    runJob<BlinkResult>('blink', apiParams(query), setProgress, ctrl.signal)
      .then(setResult)
      .catch((e) => {
        if (isAbort(e) || ctrl.signal.aborted) return;
        setError(errorText(e, t('blink.errors.timeout'), t('blink.errors.network', { url: api.defaults.baseURL })));
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.toString()]);

  const fullUrl = query ? `/?${new URLSearchParams(queryToParams(query))}` : '/';

  return (
    <div className="min-h-screen bg-[#060a14] text-gray-200 p-3 flex flex-col gap-2">
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold text-white truncate">{result?.target.name || query?.target || 'SPHEREx'}</span>
        <a href={fullUrl} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline shrink-0">
          OrbitScope ↗
        </a>
      </div>
      {!result && !error && <JobProgressBar progress={progress} />}
      {error && <div className="text-sm text-red-300">{error}</div>}
      {result && <BlinkViewer result={result} compact autoplay />}
      <div className="text-[9px] text-gray-600">NASA SPHEREx · IRSA</div>
    </div>
  );
}
