import { lazy, Suspense, useCallback, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  ChartNoAxesCombined,
  FlaskConical,
  GitCompareArrows,
  LayoutGrid,
  Menu,
  ShoppingBasket,
  X,
} from "lucide-react";

const CustomerDrawer = lazy(() => import("./components/CustomerDrawer"));
const Challenge = lazy(() => import("./pages/Challenge"));
const Directory = lazy(() => import("./pages/Directory"));
const Health = lazy(() => import("./pages/Health"));
const Paradox = lazy(() => import("./pages/Paradox"));

type Page = "directory" | "paradox" | "challenge" | "health";

const navigation = [
  {
    key: "directory",
    label: "Customer Explorer",
    icon: LayoutGrid,
    number: "01",
  },
  {
    key: "paradox",
    label: "Behavioral Paradox",
    icon: GitCompareArrows,
    number: "02",
  },
  {
    key: "challenge",
    label: "Beat the Model",
    icon: FlaskConical,
    number: "03",
  },
  { key: "health", label: "Model Pulse", icon: Activity, number: "04" },
] as const;

export default function App() {
  const [page, setPage] = useState<Page>("directory");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [customerKey, setCustomerKey] = useState<string | null>(null);
  const closeDrawer = useCallback(() => setCustomerKey(null), []);
  const selected = navigation.find((item) => item.key === page)!;

  const navigate = (next: Page) => {
    setPage(next);
    setMobileOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="app-frame">
      <aside className={`sidebar ${mobileOpen ? "mobile-open" : ""}`}>
        <div className="sidebar-top">
          <button
            className="brand-mark"
            aria-label="Open customer explorer"
            onClick={() => navigate("directory")}
          >
            <ShoppingBasket size={24} strokeWidth={2.2} />
          </button>
          <div className="brand-name">
            <strong>
              behind<span>the</span>basket
            </strong>
            <small>RETAIL INTELLIGENCE</small>
          </div>
          <button
            className="mobile-close"
            aria-label="Close navigation"
            onClick={() => setMobileOpen(false)}
          >
            <X size={19} />
          </button>
        </div>

        <div className="sidebar-label">WORKSPACE</div>
        <nav className="sidebar-nav" aria-label="Main navigation">
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                className={`nav-link ${page === item.key ? "active" : ""}`}
                onClick={() => navigate(item.key)}
                aria-current={page === item.key ? "page" : undefined}
              >
                <Icon size={20} strokeWidth={1.9} />
                <span>{item.label}</span>
                <small>{item.number}</small>
              </button>
            );
          })}
        </nav>

        <div className="sidebar-bottom">
          <div className="sidebar-insight">
            <div className="sidebar-insight-icon">
              <ChartNoAxesCombined size={18} />
            </div>
            <strong>Look beyond the basket.</strong>
            <p>
              Patterns, probabilities, and real household behavior—together.
            </p>
          </div>
          <div className="dataset-chip">
            <span className="dataset-dot" />
            <div>
              <strong>Historical dataset</strong>
              <small>Model v1 · Day 711</small>
            </div>
          </div>
        </div>
      </aside>

      {mobileOpen && (
        <button
          className="mobile-scrim"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <div className="main-frame">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu"
              aria-label="Open navigation"
              onClick={() => setMobileOpen(true)}
            >
              <Menu size={21} />
            </button>
            <span>Workspace</span>
            <span className="crumb-divider">/</span>
            <strong>{selected.label}</strong>
          </div>
          <div className="topbar-right">
            <span className="env-pill">
              <span /> Demo environment
            </span>
            <a
              href="/docs"
              className="docs-link"
              target="_blank"
              rel="noreferrer"
            >
              API Docs <ArrowUpRight size={15} />
            </a>
          </div>
        </header>

        <main id="main-content">
          <Suspense
            fallback={
              <div className="page-content">
                <div className="loading-card">
                  <span className="spinner" /> Loading workspace…
                </div>
              </div>
            }
          >
            {page === "directory" && <Directory onPick={setCustomerKey} />}
            {page === "paradox" && <Paradox onPick={setCustomerKey} />}
            {page === "challenge" && <Challenge />}
            {page === "health" && <Health />}
          </Suspense>
        </main>
        <footer className="app-footer">
          <span>BEHIND THE BASKET · RETAIL BEHAVIOR LAB</span>
          <span>Powered by PostgreSQL + LightGBM</span>
        </footer>
      </div>

      {customerKey && (
        <Suspense fallback={null}>
          <CustomerDrawer householdKey={customerKey} onClose={closeDrawer} />
        </Suspense>
      )}
    </div>
  );
}
