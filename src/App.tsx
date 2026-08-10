import { Navigate, Route, Routes } from "react-router-dom";
import ModelsAndAgents from "./pages/ModelsAndAgents";
import TestLibrary from "./pages/TestLibrary";
import Experiments from "./pages/Experiments";
import ExperimentDetail from "./pages/ExperimentDetail";
import RunDetail from "./pages/RunDetail";
import Leaderboard from "./pages/Leaderboard";
import Profiles from "./pages/Profiles";
import SettingsPage from "./pages/Settings";
import AgentFlow from "./v4/AgentFlow";
import AgentStudio from "./v4/AgentStudio";
import BenchmarksHub from "./v4/BenchmarksHub";
import ControlCenter from "./v4/ControlCenter";
import Projects from "./v4/Projects";
import Tasks from "./v4/Tasks";
import ToolsMcp from "./v4/ToolsMcp";
import V4Layout from "./v4/V4Layout";

export default function App() {
  return (
    <Routes>
      <Route element={<V4Layout />}>
        <Route index element={<ControlCenter />} />
        <Route path="projects" element={<Projects />} />
        <Route path="studio" element={<AgentStudio />} />
        <Route path="studio/:sessionId" element={<AgentStudio />} />
        <Route path="flows" element={<AgentFlow />} />
        <Route path="tasks" element={<Tasks />} />
        <Route path="tools" element={<ToolsMcp />} />
        <Route path="benchmarks" element={<BenchmarksHub />} />
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
