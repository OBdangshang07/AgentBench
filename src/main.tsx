import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router-dom";
import App from "./App";
import { AppErrorBoundary, WorkspaceUxProvider } from "./components/WorkspaceUx";
import "./design-system/index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HashRouter>
      <WorkspaceUxProvider>
        <AppErrorBoundary><App /></AppErrorBoundary>
      </WorkspaceUxProvider>
    </HashRouter>
  </React.StrictMode>,
);
