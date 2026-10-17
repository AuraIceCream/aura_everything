import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./app";
import { ErrorBoundary } from "./components/error-boundary";
import { SettingsProvider } from "./context/settings";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 20_000, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <SettingsProvider>
          <BrowserRouter><App /></BrowserRouter>
        </SettingsProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
