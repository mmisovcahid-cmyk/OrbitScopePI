import React from 'react';

export const OrbitScopeLogo: React.FC<{ className?: string }> = ({ className = 'w-9 h-9' }) => (
  <svg viewBox="0 0 48 48" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="planetGrad" x1="12" y1="12" x2="36" y2="36" gradientUnits="userSpaceOnUse">
        <stop stopColor="#38BDF8" />
        <stop offset="0.5" stopColor="#1E40AF" />
        <stop offset="1" stopColor="#0B132B" />
      </linearGradient>
      <linearGradient id="ringGrad" x1="4" y1="24" x2="44" y2="24" gradientUnits="userSpaceOnUse">
        <stop stopColor="#38BDF8" stopOpacity="0.9" />
        <stop offset="0.5" stopColor="#818CF8" stopOpacity="0.4" />
        <stop offset="1" stopColor="#38BDF8" stopOpacity="0.9" />
      </linearGradient>
      <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="2" result="blur" />
        <feComposite in="SourceGraphic" in2="blur" operator="over" />
      </filter>
    </defs>
    
    {/* Central Planet */}
    <circle cx="24" cy="24" r="11" fill="url(#planetGrad)" filter="url(#glow)" />
    
    {/* Atmospheric crescent */}
    <path
      d="M17 17 C22 13, 31 16, 33 24 C31 20, 24 17, 17 17 Z"
      fill="#7DD3FC"
      opacity="0.8"
    />

    {/* Outer tilted rings */}
    <ellipse
      cx="24"
      cy="24"
      rx="21"
      ry="7"
      stroke="url(#ringGrad)"
      strokeWidth="2.5"
      transform="rotate(-26 24 24)"
    />
  </svg>
);

export const SpherexSatelliteIllustration: React.FC<{ className?: string }> = ({ className = 'w-24 h-24' }) => (
  <svg viewBox="0 0 160 140" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="coneGrad" x1="30" y1="20" x2="130" y2="70" gradientUnits="userSpaceOnUse">
        <stop stopColor="#CBD5E1" />
        <stop offset="0.3" stopColor="#64748B" />
        <stop offset="0.8" stopColor="#1E293B" />
        <stop offset="1" stopColor="#0F172A" />
      </linearGradient>
      <linearGradient id="shieldRings" x1="80" y1="20" x2="80" y2="70" gradientUnits="userSpaceOnUse">
        <stop stopColor="#94A3B8" />
        <stop offset="1" stopColor="#334155" />
      </linearGradient>
      <linearGradient id="apertureGrad" x1="80" y1="18" x2="80" y2="38" gradientUnits="userSpaceOnUse">
        <stop stopColor="#0284C7" stopOpacity="0.8" />
        <stop offset="1" stopColor="#030712" />
      </linearGradient>
      <linearGradient id="busGrad" x1="60" y1="75" x2="100" y2="120" gradientUnits="userSpaceOnUse">
        <stop stopColor="#F59E0B" />
        <stop offset="0.6" stopColor="#D97706" />
        <stop offset="1" stopColor="#78350F" />
      </linearGradient>
      <linearGradient id="panelGrad" x1="10" y1="85" x2="50" y2="115" gradientUnits="userSpaceOnUse">
        <stop stopColor="#1E3A8A" />
        <stop offset="0.5" stopColor="#2563EB" />
        <stop offset="1" stopColor="#0F172A" />
      </linearGradient>
    </defs>

    {/* V-groove thermal radiation cones (SPHEREx trademark shield) */}
    {/* Outer cone shield */}
    <path
      d="M36 28 L124 28 L104 74 L56 74 Z"
      fill="url(#coneGrad)"
      stroke="#94A3B8"
      strokeWidth="1.2"
    />
    
    {/* Inner telescope aperture */}
    <ellipse cx="80" cy="28" rx="44" ry="12" fill="url(#apertureGrad)" stroke="#38BDF8" strokeWidth="1.5" />
    <ellipse cx="80" cy="28" rx="26" ry="7" fill="#030712" stroke="#60A5FA" strokeWidth="0.8" />
    <circle cx="80" cy="28" r="4" fill="#38BDF8" opacity="0.9" />

    {/* Stepped concentric cooling shields */}
    <path d="M42 42 Q80 50 118 42" stroke="url(#shieldRings)" strokeWidth="2" fill="none" />
    <path d="M48 56 Q80 63 112 56" stroke="url(#shieldRings)" strokeWidth="2" fill="none" />
    <path d="M54 68 Q80 74 106 68" stroke="url(#shieldRings)" strokeWidth="1.5" fill="none" />

    {/* Spacecraft Bus (Hexagonal golden service module) */}
    <polygon points="62,74 98,74 104,104 80,118 56,104" fill="url(#busGrad)" stroke="#FDE68A" strokeWidth="1" />
    
    {/* Golden multi-layer insulation facet lines */}
    <line x1="62" y1="74" x2="80" y2="118" stroke="#FDE047" strokeWidth="0.8" opacity="0.6" />
    <line x1="98" y1="74" x2="80" y2="118" stroke="#FDE047" strokeWidth="0.8" opacity="0.6" />

    {/* Solar array wings */}
    {/* Left Solar Panel */}
    <polygon points="20,86 54,78 50,102 16,110" fill="url(#panelGrad)" stroke="#60A5FA" strokeWidth="1" />
    <line x1="28" y1="84" x2="24" y2="108" stroke="#93C5FD" strokeWidth="0.6" />
    <line x1="38" y1="82" x2="34" y2="106" stroke="#93C5FD" strokeWidth="0.6" />

    {/* Right Solar Panel */}
    <polygon points="106,78 140,86 144,110 110,102" fill="url(#panelGrad)" stroke="#60A5FA" strokeWidth="1" />
    <line x1="122" y1="82" x2="126" y2="106" stroke="#93C5FD" strokeWidth="0.6" />
    <line x1="132" y1="84" x2="136" y2="108" stroke="#93C5FD" strokeWidth="0.6" />

    {/* Antenna & star tracker sensors */}
    <line x1="80" y1="118" x2="80" y2="128" stroke="#CBD5E1" strokeWidth="1.5" />
    <circle cx="80" cy="128" r="2" fill="#38BDF8" />
  </svg>
);
