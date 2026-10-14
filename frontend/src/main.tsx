import React, { lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { ThemeProvider, CssBaseline } from "@mui/material";
import { theme } from "./theme";
import "./styles.css";
import "./executive.css";
import "./premium.css";
import "./human.css";
import "./login.css";
import "./data-chips.css";
import "./tour.css";
import "./reference.css";
import "./demo.css";
import { DynamicContent } from "./dynamicContent";
const Root = lazy(() => import("./ProductionApp"));

class AppErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <main className="loading error-state" role="alert">
          <div>
            <h1>OEIS could not load</h1>
            <p>{this.state.error.message}</p>
            <button type="button" onClick={() => window.location.reload()}>
              Reload dashboard
            </button>
          </div>
        </main>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")!).render(
  <AppErrorBoundary>
    <React.StrictMode>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <DynamicContent>
          <Suspense
            fallback={
              <div className="app-boot" role="status" aria-live="polite">
                Loading OEIS dashboard…
                <span />
              </div>
            }
          >
            <Root />
          </Suspense>
        </DynamicContent>
      </ThemeProvider>
    </React.StrictMode>
  </AppErrorBoundary>,
);
