import { useEffect, useRef, useState } from "react";
import {
  X,
  ArrowUpRight,
  CalendarClock,
  ShoppingBasket,
  ReceiptText,
  Tags,
  ChartNoAxesCombined,
} from "lucide-react";
import { api } from "../api";
import type { CustomerProfile } from "../types";
import {
  currency,
  decimal,
  dnaSignals,
  featureSections,
  label,
  percent,
} from "../utils";
import HistoryChart from "./HistoryChart";

export default function CustomerDrawer({
  householdKey,
  onClose,
}: {
  householdKey: string | null;
  onClose: () => void;
}) {
  const [profile, setProfile] = useState<CustomerProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!householdKey) return;
    const controller = new AbortController();
    setLoading(true);
    setProfile(null);
    setError("");
    api
      .customer(householdKey, controller.signal)
      .then(setProfile)
      .catch((reason) => {
        if (!controller.signal.aborted) setError(String(reason.message));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [householdKey]);

  useEffect(() => {
    if (!householdKey) return;
    const lastFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", escape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", escape);
      lastFocus?.focus();
    };
  }, [householdKey, onClose]);

  if (!householdKey) return null;

  return (
    <div
      className="drawer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        className="customer-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
      >
        <div className="drawer-topbar">
          <div className="eyebrow">
            <span className="eyebrow-dot" /> CUSTOMER PROFILE
          </div>
          <button
            className="icon-button"
            aria-label="Close customer profile"
            ref={closeButton}
            onClick={onClose}
          >
            <X size={19} />
          </button>
        </div>
        <div className="drawer-scroll">
          <div className="drawer-headline">
            <div>
              <div className="overline">HOUSEHOLD ID</div>
              <h2 id="drawer-title">#{householdKey}</h2>
            </div>
            {profile && (
              <span className="tiny-pill">
                Rank #{decimal(profile.propensity_rank, 0)}
              </span>
            )}
          </div>

          {loading && (
            <div className="loading-block">
              <span className="spinner" />
              Loading full customer profile…
            </div>
          )}
          {error && (
            <div className="error-box">
              {error}
              <button className="text-link" onClick={onClose}>
                Close
              </button>
            </div>
          )}

          {profile && (
            <>
              <section className="probability-hero">
                <span className="overline">PREDICTED 7-DAY REPURCHASE</span>
                <div className="probability-figure">
                  {percent(profile.live_model_probability)}{" "}
                  <ArrowUpRight size={25} />
                </div>
                <div className="meter meter-on-dark">
                  <div
                    style={{
                      width: percent(profile.live_model_probability, 2),
                    }}
                  />
                </div>
                <div className="probability-foot">
                  <span>Model v1 · Day {profile.as_of_day}</span>
                  <span>Decile {profile.score_decile} / 10</span>
                </div>
              </section>

              <div className="drawer-stats">
                <div>
                  <ShoppingBasket size={17} />
                  <span>90-day baskets</span>
                  <strong>{decimal(profile.features.baskets_90d, 0)}</strong>
                </div>
                <div>
                  <ReceiptText size={17} />
                  <span>90-day spend</span>
                  <strong>{currency(profile.features.sales_90d)}</strong>
                </div>
                <div>
                  <CalendarClock size={17} />
                  <span>Days since visit</span>
                  <strong>{decimal(profile.features.recency_days, 0)}</strong>
                </div>
              </div>

              <section className="drawer-section">
                <div className="section-head compact">
                  <div>
                    <span className="overline">SPENDING OVER TIME</span>
                    <h3>Shopping pulse</h3>
                  </div>
                  <span className="tiny-pill">Past 90 days</span>
                </div>
                <HistoryChart events={profile.purchase_history} height={195} />
              </section>

              <section className="drawer-section">
                <div className="section-head compact">
                  <div>
                    <span className="overline">RELATIVE TO THE COHORT</span>
                    <h3>Shopping DNA</h3>
                  </div>
                  <ChartNoAxesCombined size={19} className="icon-muted" />
                </div>
                <div className="dna-list">
                  {dnaSignals.map((signal) => {
                    const value = profile.dna[signal.key];
                    return (
                      <div className="dna-row" key={signal.key}>
                        <div className="dna-label">
                          <span>{signal.title}</span>
                          <strong>
                            {value == null ? "N/A" : `${decimal(value, 0)}th`}
                          </strong>
                        </div>
                        <div className="meter">
                          <div
                            style={{
                              width: `${Math.max(0, Math.min(100, value ?? 0))}%`,
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>

              <section className="drawer-section last">
                <div className="section-head compact">
                  <div>
                    <span className="overline">MODEL INPUTS</span>
                    <h3>All 15 behavioral signals</h3>
                  </div>
                  <Tags size={19} className="icon-muted" />
                </div>
                {featureSections.map((section) => (
                  <details className="feature-group" key={section.heading}>
                    <summary>
                      {section.heading}
                      <span>{section.names.length} features</span>
                    </summary>
                    <div className="feature-grid">
                      {section.names.map((name) => (
                        <div key={name}>
                          <span>{label(name)}</span>
                          <strong>{decimal(profile.features[name], 2)}</strong>
                        </div>
                      ))}
                    </div>
                  </details>
                ))}
              </section>
              <p className="drawer-disclaimer">
                Model scores describe purchase propensity, not the effect of an
                offer or campaign. Customer identifiers are from a historical
                research dataset.
              </p>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
