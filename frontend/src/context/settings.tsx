import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { ContextDepth, LearnerLevel, TeachingMode } from "../types";

export interface Settings {
  learnerLevel: LearnerLevel;
  teachingMode: TeachingMode;
  responseLength: "concise" | "balanced" | "detailed";
  contextDepth: ContextDepth;
  localModel: string;
  developerMode: boolean;
  externalCritic: boolean;
}

const defaults: Settings = {
  learnerLevel: "undergraduate",
  teachingMode: "guided",
  responseLength: "balanced",
  contextDepth: "expanded",
  localModel: "Qwen 3.6 local",
  developerMode: false,
  externalCritic: false,
};

interface SettingsContextValue {
  settings: Settings;
  update: (patch: Partial<Settings>) => void;
  reset: () => void;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

function readSettings(): Settings {
  try {
    const value = localStorage.getItem("aura-bio-settings");
    return value ? { ...defaults, ...(JSON.parse(value) as Partial<Settings>) } : defaults;
  } catch {
    return defaults;
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(readSettings);
  useEffect(() => localStorage.setItem("aura-bio-settings", JSON.stringify(settings)), [settings]);
  const value = useMemo<SettingsContextValue>(
    () => ({
      settings,
      update: (patch) => setSettings((current) => ({ ...current, ...patch })),
      reset: () => setSettings(defaults),
    }),
    [settings],
  );
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings() {
  const value = useContext(SettingsContext);
  if (!value) throw new Error("useSettings must be used within SettingsProvider");
  return value;
}

