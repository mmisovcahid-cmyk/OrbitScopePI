import { Suspense, lazy } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Sparkles,
  Telescope,
  Crosshair,
  GitCompare,
  Orbit,
  BarChart2,
  BookOpen,
  Users,
  Globe,
  RadioTower
} from 'lucide-react';
import { OrbitScopeLogo, SpherexSatelliteIllustration } from './Icons';
import OfflineBanner from './OfflineBanner';
import { isKiosk } from '../../lib/kiosk';

// Only the Pi's own screen needs the QR codes (and the QR library).
const KioskConnectCard = lazy(() => import('./KioskConnectCard'));

export default function Layout() {
  const { t, i18n } = useTranslation();
  const location = useLocation();

  const toggleLanguage = () => {
    i18n.changeLanguage(i18n.language === 'en' ? 'az' : 'en');
  };

  const sidebarLinks = [
    { to: '/', icon: Sparkles, label: t('nav.blink') },
    { to: '/dashboard', icon: Telescope, label: t('nav.dashboard') },
    { to: '/detection', icon: Crosshair, label: t('nav.detection') },
    { to: '/comparison', icon: GitCompare, label: t('nav.comparison') },
    { to: '/planetx', icon: Orbit, label: t('nav.planetx') },
    { to: '/catalog', icon: BarChart2, label: t('nav.catalog') },
    { to: '/ground', icon: RadioTower, label: t('nav.ground') },
    { to: '/about', icon: BookOpen, label: t('nav.about') },
  ];

  return (
    <div className="flex flex-col h-screen w-full bg-[#060a14] text-gray-200 overflow-hidden font-sans">
      {/* ============================================================ */}
      {/* TOP HEADER */}
      {/* ============================================================ */}
      <header className="h-16 px-6 border-b border-white/[0.08] bg-[#070b18]/90 backdrop-blur-md flex items-center justify-between shrink-0 z-50">
        {/* Left: OrbitScope branding (no NASA insignia: its use needs NASA's permission) */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-3">
            <OrbitScopeLogo className="w-9 h-9" />
            <div>
              <div className="text-lg font-bold text-white tracking-tight leading-none">
                OrbitScope
              </div>
              <div className="text-[11px] text-gray-400 mt-1 leading-none font-medium">
                SPHEREx Time-Domain Sky Monitor
              </div>
            </div>
          </div>
        </div>

        {/* Right: Controls & Space Apps pill */}
        <div className="flex items-center gap-2 md:gap-4">
          {/* Language toggle (AZ / EN) */}
          <button
            onClick={toggleLanguage}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-white/5 hover:bg-white/10 border border-white/10 text-gray-200 transition-colors"
          >
            <Globe className="w-3.5 h-3.5 text-sky-400" />
            <span>{i18n.language === 'en' ? 'AZ' : 'EN'}</span>
          </button>

          {/* NASA Space Apps pill button */}
          <div className={`${isKiosk ? 'hidden' : 'hidden sm:flex'} items-center gap-2 px-3 py-1.5 rounded-xl bg-sky-500/10 border border-sky-500/20 text-sky-400 text-xs font-medium`}>
            <Users className="w-3.5 h-3.5" />
            <span>NASA Space Apps</span>
          </div>
        </div>
      </header>
      <OfflineBanner />

      {/* ============================================================ */}
      {/* BODY (SIDEBAR + MAIN CONTENT) */}
      {/* ============================================================ */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* ============================================================ */}
        {/* LEFT SIDEBAR */}
        {/* ============================================================ */}
        <aside className="hidden md:flex w-56 border-r border-white/[0.08] bg-[#070b18]/70 backdrop-blur-md flex flex-col justify-between p-4 shrink-0 z-40 relative">
          {/* Top navigation buttons */}
          <div className="space-y-1.5">
            {sidebarLinks.map((link) => {
              const isActive = location.pathname === link.to;
              const Icon = link.icon;
              return (
                <NavLink
                  key={link.to}
                  to={link.to}
                  className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-medium transition-all ${
                    isActive
                      ? 'bg-gradient-to-r from-blue-600/30 to-sky-600/20 border border-sky-500/40 text-sky-400 shadow-[0_0_15px_rgba(56,189,248,0.2)]'
                      : 'text-gray-400 hover:text-gray-200 hover:bg-white/[0.03]'
                  }`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span>{link.label}</span>
                </NavLink>
              );
            })}
          </div>

          {/* Bottom Card: Powered by NASA SPHEREx */}
          <div className="space-y-3 pt-4">
            <div className="rounded-2xl bg-gradient-to-b from-[#0b1329] to-[#080d1e] border border-white/[0.09] p-3.5 relative overflow-hidden shadow-2xl">
              <div className="text-[10px] text-gray-400 font-medium">Powered by</div>
              <div className="text-xs font-bold text-white tracking-wide">NASA SPHEREx</div>

              {/* SPHEREx Telescope Illustration */}
              <div className="my-2 flex justify-center">
                <SpherexSatelliteIllustration className="w-24 h-20 drop-shadow-[0_0_15px_rgba(56,189,248,0.25)]" />
              </div>

              <div className="text-[10px] text-sky-300/80 leading-tight">
                All-sky survey in 102 infrared bands
              </div>
            </div>

            {/* Tagline */}
            <div className="text-[11px] italic font-serif text-gray-400 text-center tracking-wide">
              Explore. Analyze. Discover.
            </div>
          </div>

          {/* Atmospheric Earth Limb Glow (Bottom Left) */}
          <div
            className="absolute -bottom-16 -left-16 w-48 h-48 rounded-full pointer-events-none opacity-40 blur-2xl"
            style={{
              background: 'radial-gradient(circle, #38bdf8 0%, #1e40af 60%, transparent 100%)',
            }}
          />
        </aside>

        {/* ============================================================ */}
        {/* MAIN OUTLET CONTAINER */}
        {/* ============================================================ */}
        <main className="flex-1 overflow-y-auto bg-[#060a14] relative min-w-0">
          {/* Mobile navigation (sidebar is hidden below md) */}
          <nav className="md:hidden flex gap-1 overflow-x-auto px-3 py-2 border-b border-white/[0.08] bg-[#070b18]">
            {sidebarLinks.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.to === '/'}
                className={({ isActive }) => `shrink-0 px-3 py-1.5 rounded-lg text-xs ${isActive ? 'bg-sky-500/20 text-sky-300' : 'text-gray-400'}`}
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          <Outlet />
        </main>
      </div>
      {isKiosk && <Suspense fallback={null}><KioskConnectCard /></Suspense>}
    </div>
  );
}
