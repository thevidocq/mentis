import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { CurrentTenantProvider } from "./auth/currentTenant";
import { installResponsiveTables } from "./components/responsiveTables";
import "./styles/base.css";

installResponsiveTables();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <CurrentTenantProvider>
          <App />
        </CurrentTenantProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
