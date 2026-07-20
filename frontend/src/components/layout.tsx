import { useQuery } from "@tanstack/react-query";
import { Activity, Atom, BookOpen, Database, FlaskConical, Menu, MessageCircleQuestion, PanelLeftClose, PanelLeftOpen, Settings, X } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../lib/api";
import { ActivityCenter } from "./activity-center";
import { StatusPill } from "./ui";

const navigation = [
  { to: "/ask", label: "Ask AURA", icon: MessageCircleQuestion },
  { to: "/retrieval", label: "Retrieval lab", icon: FlaskConical },
  { to: "/traces/run-demo-4821", label: "Pipeline traces", icon: Activity },
  { to: "/corpus", label: "Corpus", icon: Database },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => localStorage.getItem("aura-sidebar-open") !== "false");
  const [sidebarPreview, setSidebarPreview] = useState(false);
  const location = useLocation();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15_000 });
  const status = health.data?.status ?? "offline";
  const currentPage = navigation.find((item) => location.pathname.startsWith(item.to.split("/run-")[0]))?.label ?? "AURA Bio";

  useEffect(() => {
    localStorage.setItem("aura-sidebar-open", String(sidebarOpen));
  }, [sidebarOpen]);

  useEffect(() => {
    if (!sidebarPreview) return;
    const closePreviewOutsideNavigation = (event: MouseEvent) => {
      const target = event.target as Element;
      if (!target.closest(".sidebar") && !target.closest(".sidebar-open")) setSidebarPreview(false);
    };
    document.addEventListener("mousemove", closePreviewOutsideNavigation);
    return () => document.removeEventListener("mousemove", closePreviewOutsideNavigation);
  }, [sidebarPreview]);

  return (
    <div className={sidebarOpen ? "app-shell" : "app-shell sidebar-collapsed"}>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside
        className={`sidebar${mobileOpen ? " is-open" : ""}${sidebarPreview ? " is-preview" : ""}`}
        aria-hidden={!sidebarOpen && !sidebarPreview && !mobileOpen}
        onMouseLeave={() => setSidebarPreview(false)}
      >
        <div className="brand">
          <div className="brand-mark"><Atom size={21} /></div>
          <div><strong>AURA<span>Bio</span></strong><small>Biology research tutor</small></div>
          <button className="icon-button sidebar-close desktop-only" onClick={() => { setSidebarOpen(!sidebarOpen); setSidebarPreview(false); }} aria-label={sidebarOpen ? "Close sidebar" : "Keep sidebar open"} title={sidebarOpen ? "Close sidebar" : "Keep sidebar open"}>{sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}</button>
          <button className="icon-button mobile-only" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X size={18} /></button>
        </div>
        <nav aria-label="Primary navigation">
          <span className="nav-label">Workspace</span>
          {navigation.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} onClick={() => setMobileOpen(false)} className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}>
              <Icon size={18} /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-card">
          <BookOpen size={17} />
          <div><strong>Corpus processing</strong><span>Chunking continues on D:</span></div>
          <div className="mini-progress"><span style={{ width: "99%" }} /></div>
        </div>
        <div className="sidebar-footer"><span className="privacy-dot" />Private by default<small>External critique is opt-in</small></div>
      </aside>
      <div className="app-column">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu size={19} /></button>
          {!sidebarOpen && <button className="icon-button sidebar-open desktop-only" onMouseEnter={() => setSidebarPreview(true)} onClick={() => { setSidebarOpen(true); setSidebarPreview(false); }} aria-label="Open sidebar" title="Hover to preview · click to keep open"><Menu size={19} /></button>}
          <div className="topbar__context"><strong>{currentPage}</strong><span>Hybrid workspace</span></div>
          <div className="topbar__status">
            <span className="model-label"><span className="pulse-dot" />Qwen 3.6 <i>·</i> GLM optional</span>
            <StatusPill tone={status === "ready" ? "success" : status === "partial" ? "warning" : "danger"}>
              {status === "ready" ? "System ready" : status === "partial" ? "Partial index" : "Backend offline"}
            </StatusPill>
            <ActivityCenter />
          </div>
        </header>
        <main id="main-content" className="main-content"><Outlet /></main>
      </div>
      {mobileOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
    </div>
  );
}
