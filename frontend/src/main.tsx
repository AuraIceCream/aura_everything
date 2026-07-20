import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./app";
import { SettingsProvider } from "./context/settings";
import { USE_MOCKS } from "./lib/api";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 20_000, refetchOnWindowFocus: false } },
});

async function start() {
  if (USE_MOCKS) {
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledRequest: "bypass", quiet: true });
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <SettingsProvider>
          <BrowserRouter><App /></BrowserRouter>
        </SettingsProvider>
      </QueryClientProvider>
    </StrictMode>,
  );
}

void start();

