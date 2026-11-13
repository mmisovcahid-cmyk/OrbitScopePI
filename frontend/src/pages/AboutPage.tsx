import { useTranslation } from 'react-i18next';
import { BookOpen, Layers, ShieldCheck, Database, Award, Activity, Info } from 'lucide-react';

export default function AboutPage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-8 max-w-5xl mx-auto p-4 md:p-6 pb-10">
      {/* Hero / Header */}
      <div>
        <h1 className="text-3xl font-bold text-white flex items-center gap-3">
          <BookOpen className="w-8 h-8 text-blue-400" />
          {t('about.title')}
        </h1>
        <p className="text-base text-gray-400 mt-2">{t('about.subtitle')}</p>
      </div>

      {/* Platform Overview */}
      <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Activity className="w-5 h-5 text-blue-400" />
          {t('about.overview.title')}
        </h2>
        <p className="text-sm text-gray-300 leading-relaxed">
          {t('about.overview.description')}
        </p>
        <p className="text-sm text-gray-400 leading-relaxed italic border-l-2 border-blue-500/40 pl-4 py-1">
          {t('about.overview.mission')}
        </p>
      </div>

      {/* Scientific Methodology */}
      <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6 space-y-6">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Layers className="w-5 h-5 text-indigo-400" />
          {t('about.methodology.title')}
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
          <div className="p-4 rounded-lg bg-white/[0.02] border border-white/5 space-y-2">
            <div className="flex items-center gap-2 font-semibold text-blue-400">
              <span className="w-5 h-5 rounded-full bg-blue-500/20 flex items-center justify-center text-[10px]">1</span>
              {t('about.methodology.step1Title')}
            </div>
            <p className="text-gray-400 leading-relaxed">{t('about.methodology.step1Desc')}</p>
          </div>

          <div className="p-4 rounded-lg bg-white/[0.02] border border-white/5 space-y-2">
            <div className="flex items-center gap-2 font-semibold text-blue-400">
              <span className="w-5 h-5 rounded-full bg-blue-500/20 flex items-center justify-center text-[10px]">2</span>
              {t('about.methodology.step2Title')}
            </div>
            <p className="text-gray-400 leading-relaxed">{t('about.methodology.step2Desc')}</p>
          </div>

          <div className="p-4 rounded-lg bg-white/[0.02] border border-white/5 space-y-2">
            <div className="flex items-center gap-2 font-semibold text-blue-400">
              <span className="w-5 h-5 rounded-full bg-blue-500/20 flex items-center justify-center text-[10px]">3</span>
              {t('about.methodology.step3Title')}
            </div>
            <p className="text-gray-400 leading-relaxed">{t('about.methodology.step3Desc')}</p>
          </div>

          <div className="p-4 rounded-lg bg-white/[0.02] border border-white/5 space-y-2">
            <div className="flex items-center gap-2 font-semibold text-blue-400">
              <span className="w-5 h-5 rounded-full bg-blue-500/20 flex items-center justify-center text-[10px]">4</span>
              {t('about.methodology.step4Title')}
            </div>
            <p className="text-gray-400 leading-relaxed">{t('about.methodology.step4Desc')}</p>
          </div>
        </div>

        <div className="p-4 rounded-lg bg-white/[0.02] border border-white/5 space-y-2 text-xs">
          <div className="flex items-center gap-2 font-semibold text-blue-400">
            <span className="w-5 h-5 rounded-full bg-blue-500/20 flex items-center justify-center text-[10px]">5</span>
            {t('about.methodology.step5Title')}
          </div>
          <p className="text-gray-400 leading-relaxed">{t('about.methodology.step5Desc')}</p>
        </div>
      </div>

      {/* Data Sources */}
      <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Database className="w-5 h-5 text-emerald-400" />
          {t('about.dataSources.title')}
        </h2>

        <div className="space-y-3 text-xs">
          <div className="flex items-start gap-3 p-3 rounded-lg bg-white/[0.01] border border-white/5">
            <span className="font-semibold text-emerald-400 shrink-0 w-24">NASA SPHEREx:</span>
            <span className="text-gray-300">{t('about.dataSources.spherex')}</span>
          </div>

          <div className="flex items-start gap-3 p-3 rounded-lg bg-white/[0.01] border border-white/5">
            <span className="font-semibold text-emerald-400 shrink-0 w-24">NASA/JPL SBDB:</span>
            <span className="text-gray-300">{t('about.dataSources.jpl')}</span>
          </div>

          <div className="flex items-start gap-3 p-3 rounded-lg bg-white/[0.01] border border-white/5">
            <span className="font-semibold text-emerald-400 shrink-0 w-24">IAU MPC:</span>
            <span className="text-gray-300">{t('about.dataSources.mpc')}</span>
          </div>

          <div className="flex items-start gap-3 p-3 rounded-lg bg-white/[0.01] border border-white/5">
            <span className="font-semibold text-emerald-400 shrink-0 w-24">ESA Gaia:</span>
            <span className="text-gray-300">{t('about.dataSources.gaia')}</span>
          </div>
        </div>

        <div className="p-3.5 rounded-lg bg-amber-500/5 border border-amber-500/20 text-xs text-amber-300 flex items-start gap-2.5">
          <Info className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{t('about.dataSources.note')}</span>
        </div>
      </div>

      {/* Limitations and Disclaimers */}
      <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <ShieldCheck className="w-5 h-5 text-amber-400" />
          {t('about.limitations.title')}
        </h2>

        <ul className="list-disc list-inside space-y-2 text-xs text-gray-400">
          <li>{t('about.limitations.item1')}</li>
          <li>{t('about.limitations.item2')}</li>
          <li>{t('about.limitations.item3')}</li>
          <li>{t('about.limitations.item4')}</li>
          <li>{t('about.limitations.item5')}</li>
        </ul>
      </div>

      {/* Credits & External Links */}
      <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Award className="w-5 h-5 text-violet-400" />
          {t('about.credits.title')}
        </h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
          <div className="p-3 rounded-lg bg-white/[0.01] border border-white/5">
            <div className="font-medium text-white">{t('about.credits.spherexTeam')}</div>
            <div className="text-gray-500 mt-0.5">NASA Jet Propulsion Laboratory & Caltech</div>
          </div>
          <div className="p-3 rounded-lg bg-white/[0.01] border border-white/5">
            <div className="font-medium text-white">{t('about.credits.jplSSD')}</div>
            <div className="text-gray-500 mt-0.5">Solar System Dynamics API & Horizons</div>
          </div>
        </div>

        <div className="text-xs text-gray-500 pt-2 border-t border-white/5">
          {t('about.credits.license')}
        </div>
      </div>
    </div>
  );
}
