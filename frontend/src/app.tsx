import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/layout";

const AskPage = lazy(() => import("./pages/AskPage").then((module) => ({ default: module.AskPage })));
const CorpusPage = lazy(() => import("./pages/CorpusPage").then((module) => ({ default: module.CorpusPage })));
const RetrievalPage = lazy(() => import("./pages/RetrievalPage").then((module) => ({ default: module.RetrievalPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const TracePage = lazy(() => import("./pages/TracePage").then((module) => ({ default: module.TracePage })));

export function App() {
  return (
    <Suspense fallback={<div className="route-loader" role="status"><span />Loading workspace…</div>}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/ask" replace />} />
          <Route path="ask" element={<AskPage />} />
          <Route path="retrieval" element={<RetrievalPage />} />
          <Route path="traces/:runId" element={<TracePage />} />
          <Route path="corpus" element={<CorpusPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/ask" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
