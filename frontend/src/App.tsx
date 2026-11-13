import { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/common/Layout';
import LoadingSpinner from './components/common/LoadingSpinner';

const BlinkPage = lazy(() => import('./pages/BlinkPage'));
const EmbedPage = lazy(() => import('./pages/EmbedPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const DetectionPage = lazy(() => import('./pages/DetectionPage'));
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'));
const ComparisonPage = lazy(() => import('./pages/ComparisonPage'));
const PlanetXPage = lazy(() => import('./pages/PlanetXPage'));
const CatalogPage = lazy(() => import('./pages/CatalogPage'));
const AboutPage = lazy(() => import('./pages/AboutPage'));

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<LoadingSpinner />}>
        <Routes>
          <Route path="/embed" element={<EmbedPage />} />
          <Route element={<Layout />}>
            <Route path="/" element={<BlinkPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/detection" element={<DetectionPage />} />
            <Route path="/analysis/:id" element={<AnalysisPage />} />
            <Route path="/comparison" element={<ComparisonPage />} />
            <Route path="/planetx" element={<PlanetXPage />} />
            <Route path="/catalog" element={<CatalogPage />} />
            <Route path="/about" element={<AboutPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
