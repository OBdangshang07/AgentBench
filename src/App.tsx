import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

const ModelsAndAgents = lazy(() => import("./pages/ModelsAndAgents"));
const TestLibrary = lazy(() => import("./pages/TestLibrary"));
const Experiments = lazy(() => import("./pages/Experiments"));
const ExperimentDetail = lazy(() => import("./pages/ExperimentDetail"));
const RunDetail = lazy(() => import("./pages/RunDetail"));
const FrontendPortfolio = lazy(() => import("./pages/FrontendPortfolio"));
const Leaderboard = lazy(() => import("./pages/Leaderboard"));
const Profiles = lazy(() => import("./pages/Profiles"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const AgentFlow = lazy(() => import("./v4/AgentFlow"));
const AgentStudio = lazy(() => import("./v4/AgentStudio"));
const BenchmarksHub = lazy(() => import("./v4/BenchmarksHub"));
const ControlCenter = lazy(() => import("./v4/ControlCenter"));
const Projects = lazy(() => import("./v4/Projects"));
const ProjectDetail = lazy(() => import("./v4/ProjectDetail"));
const Tasks = lazy(() => import("./v4/Tasks"));
const TaskDetail = lazy(() => import("./v4/TaskDetail"));
const ToolsMcp = lazy(() => import("./v4/ToolsMcp"));
const V4Layout = lazy(() => import("./v4/V4Layout"));

function RouteFallback() {
  return <div className="v5-route-loading" role="status"><span /><strong>正在载入本地工作区</strong><small>LOCAL MODULE</small></div>;
}

function deferred(element: ReactNode) {
  return <Suspense fallback={<RouteFallback />}>{element}</Suspense>;
}

export default function App() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route element={<V4Layout />}>
          <Route index element={deferred(<ControlCenter />)} />
          <Route path="projects" element={deferred(<Projects />)} />
          <Route path="projects/:projectId" element={deferred(<ProjectDetail />)} />
          <Route path="studio" element={deferred(<AgentStudio />)} />
          <Route path="studio/:sessionId" element={deferred(<AgentStudio />)} />
          <Route path="flows" element={deferred(<AgentFlow />)} />
          <Route path="tasks" element={deferred(<Tasks />)} />
          <Route path="tasks/:taskId" element={deferred(<TaskDetail />)} />
          <Route path="tools" element={deferred(<ToolsMcp />)} />
          <Route path="benchmarks" element={deferred(<BenchmarksHub />)} />
          <Route path="models" element={deferred(<ModelsAndAgents />)} />
          <Route path="library" element={deferred(<TestLibrary />)} />
          <Route path="experiments" element={deferred(<Experiments />)} />
          <Route path="experiments/:experimentId" element={deferred(<ExperimentDetail />)} />
          <Route path="experiments/:experimentId/portfolio" element={deferred(<FrontendPortfolio />)} />
          <Route path="runs/:runId" element={deferred(<RunDetail />)} />
          <Route path="leaderboard" element={deferred(<Leaderboard />)} />
          <Route path="profiles" element={deferred(<Profiles />)} />
          <Route path="settings" element={deferred(<SettingsPage />)} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
