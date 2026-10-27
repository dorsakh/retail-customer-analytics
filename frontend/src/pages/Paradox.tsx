import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  ChevronDown,
  GitCompareArrows,
  Info,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { api } from "../api";
import type { ParadoxPair } from "../types";
import { decimal, label, percent } from "../utils";

export default function Paradox({ onPick }: { onPick: (key: string) => void }) {
  const [pairs, setPairs] = useState<ParadoxPair[]>([]);
  const [expanded, setExpanded] = useState<number | null>(0);
  const [refreshToken, setRefreshToken] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api
      .paradoxes(controller.signal)
      .then((data) => {
        setPairs(data);
        setExpanded(data.length ? 0 : null);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(String(reason.message));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [refreshToken]);

  return (
    <div className="page-content">
      <div className="page-heading split-heading">
        <div>
          <div className="eyebrow">
            <span className="eyebrow-dot" /> MODEL INSIGHTS / 02
          </div>
          <h1>
            Behavioral <em>Paradox.</em>
          </h1>
          <p>
            Similar shopping histories. Different predicted futures. Explore
            what the model sees beyond basic recency and frequency.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={loading}
          onClick={() => setRefreshToken((n) => n + 1)}
        >
          <RefreshCw size={17} /> Refresh comparisons
        </button>
      </div>

      <div className="insight-banner">
        <div className="insight-icon">
          <Sparkles size={21} />
        </div>
        <div>
          <strong>The interesting cases are in the details.</strong>
          <p>
            Pairs share the same recency and differ by at most two baskets over
            90 days. Expand any pair, or open either customer's full profile
            here without leaving this page.
          </p>
        </div>
      </div>

      {loading && (
        <div className="loading-card">
          <span className="spinner" /> Finding comparable households…
        </div>
      )}
      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}
      {!loading && !error && pairs.length === 0 && (
        <div className="empty-state">
          No matching pairs met the current criteria.
        </div>
      )}

      <div className="paradox-list">
        {pairs.map((pair, index) => {
          const open = expanded === index;
          return (
            <article
              className={`paradox-card ${open ? "expanded" : ""}`}
              key={`${pair.high_household}-${pair.low_household}`}
            >
              <div className="paradox-card-top">
                <span className="pair-index">
                  COMPARISON {String(index + 1).padStart(2, "0")}
                </span>
                <span className="gap-chip">
                  <GitCompareArrows size={15} />{" "}
                  {decimal(pair.probability_gap * 100, 1)}-point gap
                </span>
              </div>
              <div className="pair-layout">
                <div className="pair-person">
                  <span className="person-overline">HIGHER PROPENSITY</span>
                  <div className="pair-name">
                    Household #{pair.high_household}
                  </div>
                  <strong>{percent(pair.high_probability)}</strong>
                  <div className="prob-bar">
                    <div style={{ width: percent(pair.high_probability) }} />
                  </div>
                  <button
                    className="profile-action"
                    onClick={() => onPick(pair.high_household)}
                  >
                    Open full profile <ArrowUpRight size={16} />
                  </button>
                </div>
                <div className="pair-vs">
                  <span>VS</span>
                </div>
                <div className="pair-person lower">
                  <span className="person-overline">LOWER PROPENSITY</span>
                  <div className="pair-name">
                    Household #{pair.low_household}
                  </div>
                  <strong>{percent(pair.low_probability)}</strong>
                  <div className="prob-bar">
                    <div style={{ width: percent(pair.low_probability) }} />
                  </div>
                  <button
                    className="profile-action"
                    onClick={() => onPick(pair.low_household)}
                  >
                    Open full profile <ArrowUpRight size={16} />
                  </button>
                </div>
              </div>
              <div className="pair-common">
                <span>
                  Shared recency: <strong>{pair.recency_days} days</strong>
                </span>
                <span>
                  90-day baskets:{" "}
                  <strong>
                    {pair.high_baskets_90d} vs {pair.low_baskets_90d}
                  </strong>
                </span>
              </div>

              <button
                className="pair-expand"
                aria-expanded={open}
                onClick={() => setExpanded(open ? null : index)}
              >
                <span>
                  {open
                    ? "Hide comparison details"
                    : "Why does the model disagree?"}
                </span>
                <ChevronDown size={19} className={open ? "rotated" : ""} />
              </button>
              {open && (
                <div className="pair-evidence">
                  <div className="evidence-head">
                    <div>
                      <h3>Features behind the gap</h3>
                      <p>
                        Largest differences in LightGBM raw-score contributions.
                      </p>
                    </div>
                    <Info size={18} />
                  </div>
                  <div className="evidence-table">
                    <div className="evidence-th">
                      <span>FEATURE</span>
                      <span>HIGHER</span>
                      <span>LOWER</span>
                      <span>RAW Δ</span>
                    </div>
                    {pair.top_differences.map((difference) => (
                      <div className="evidence-tr" key={difference.feature}>
                        <span>{label(difference.feature)}</span>
                        <strong>
                          {decimal(difference.higher_customer_value, 2)}
                        </strong>
                        <strong>
                          {decimal(difference.lower_customer_value, 2)}
                        </strong>
                        <strong className="delta">
                          {difference.raw_score_difference > 0 ? "+" : ""}
                          {decimal(difference.raw_score_difference, 3)}
                        </strong>
                      </div>
                    ))}
                  </div>
                  <div className="comparison-actions">
                    <button
                      className="outline-button"
                      onClick={() => onPick(pair.high_household)}
                    >
                      Inspect #{pair.high_household}
                    </button>
                    <button
                      className="outline-button"
                      onClick={() => onPick(pair.low_household)}
                    >
                      Inspect #{pair.low_household}
                    </button>
                  </div>
                  <p className="detail-disclaimer">
                    Raw contributions use log-odds units. They explain model
                    behavior, not causal effects on purchasing.
                  </p>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
