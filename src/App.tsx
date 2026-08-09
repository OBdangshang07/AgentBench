import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import ModelsAndAgents from "./pages/ModelsAndAgents";
import TestLibrary from "./pages/TestLibrary";
import Experiments from "./pages/Experiments";
import ExperimentDetail from "./pages/ExperimentDetail";
import RunDetail from "./pages/RunDetail";
import Leaderboard from "./pages/Leaderboard";
import Profiles from "./pages/Profiles";
import SettingsPage from "./pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="models" element={<ModelsAndAgents />} />
        <Route path="library" element={<TestLibrary />} />
        <Route path="experiments" element={<Experiments />} />
        <Route path="experiments/:experimentId" element={<ExperimentDetail />} />
        <Route path="runs/:runId" element={<RunDetail />} />
        <Route path="leaderboard" element={<Leaderboard />} />
        <Route path="profiles" element={<Profiles />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
