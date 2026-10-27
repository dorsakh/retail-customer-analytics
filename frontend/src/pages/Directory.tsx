import { useEffect, useState } from "react";
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Database,
  Search,
  SlidersHorizontal,
  UsersRound,
} from "lucide-react";
import { api } from "../api";
import type { DirectoryResponse } from "../types";
import { decimal, percent } from "../utils";

const LIMIT = 16;

export default function Directory({
  onPick,
}: {
  onPick: (key: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("rank");
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<DirectoryResponse | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(draft.trim());
      setOffset(0);
    }, 280);
    return () => window.clearTimeout(timer);
  }, [draft]);

  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError("");
    api
      .directory({ q: query, offset, limit: LIMIT, sort }, controller.signal)
      .then(setResult)
      .catch((reason) => {
        if (!controller.signal.aborted) setError(String(reason.message));
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [query, offset, sort]);

  const total = result?.total ?? 0;

  return (
    <div className="page-content">
      <div className="page-hero">
        <div>
          <div className="eyebrow">
            <span className="eyebrow-dot" /> CUSTOMER INTELLIGENCE / 01
          </div>
          <h1>
            People are patterns.
            <br />
            <em>Explore the story.</em>
          </h1>
          <p>
            Browse actual scored households, inspect their purchasing history,
            and see the 15 signals behind each prediction.
          </p>
          <div className="hero-tags">
            <span>Historical retail cohort</span>
            <span>7-day repurchase</span>
            <span>Model v1</span>
          </div>
        </div>
        <div className="hero-orbit" aria-hidden="true">
          <div className="orbit outer" />
          <div className="orbit inner" />
          <div className="orbit-core">
            <Database size={35} strokeWidth={1.6} />
          </div>
          <span className="orbit-point a" />
          <span className="orbit-point b" />
        </div>
      </div>

      <div className="metric-grid">
        <div className="metric-tile">
          <div className="metric-icon green">
            <UsersRound size={19} />
          </div>
          <span>Scored customers</span>
          <strong>
            {result && !query
              ? decimal(result.total, 0)
              : query
                ? "Search"
                : "—"}
          </strong>
          <small>At observation day 711</small>
        </div>
        <div className="metric-tile">
          <div className="metric-icon blue">
            <SlidersHorizontal size={19} />
          </div>
          <span>Behavioral indicators</span>
          <strong>15</strong>
          <small>Calculated from purchase history</small>
        </div>
        <div className="metric-tile">
          <div className="metric-icon orange">
            <Database size={19} />
          </div>
          <span>Scoring window</span>
          <strong>7 days</strong>
          <small>Likelihood of a return visit</small>
        </div>
      </div>

      <section className="directory-card">
        <div className="directory-header">
          <div>
            <div className="eyebrow muted-eyebrow">
              INTERACTIVE CUSTOMER INDEX
            </div>
            <h2>Customer directory</h2>
            <p>
              Search across the full scored cohort—not just the highest-ranked
              shoppers.
            </p>
          </div>
          <span className="directory-count">
            {result ? `${decimal(result.total, 0)} records` : "Loading records"}
          </span>
        </div>
        <div className="directory-controls">
          <label className="search-field">
            <Search size={19} />
            <input
              aria-label="Search household ID"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Search any household ID..."
            />
          </label>
          <label className="select-field">
            Sort by
            <select
              aria-label="Sort customers"
              value={sort}
              onChange={(event) => {
                setSort(event.target.value);
                setOffset(0);
              }}
            >
              <option value="rank">Highest propensity</option>
              <option value="household">Household ID</option>
              <option value="probability">Model probability</option>
            </select>
          </label>
        </div>

        {error && (
          <div className="inline-message error-box" role="alert">
            {error}
          </div>
        )}

        <div className="table-scroll">
          <table className="directory-table">
            <thead>
              <tr>
                <th>HOUSEHOLD</th>
                <th>7-DAY LIKELIHOOD</th>
                <th>PROPENSITY</th>
                <th>ACTIVITY PERCENTILE</th>
                <th className="table-action">PROFILE</th>
              </tr>
            </thead>
            <tbody>
              {result?.items.map((customer) => (
                <tr key={customer.household_key}>
                  <td>
                    <button
                      className="household-link"
                      onClick={() => onPick(customer.household_key)}
                    >
                      <span className="person-mark">
                        {customer.household_key.slice(-2)}
                      </span>
                      <span>
                        #{customer.household_key}
                        <small>
                          Rank {decimal(customer.propensity_rank, 0)}
                        </small>
                      </span>
                    </button>
                  </td>
                  <td>
                    <span className="likelihood-value">
                      {percent(customer.predicted_probability)}
                    </span>
                    <div className="meter table-meter">
                      <div
                        style={{
                          width: percent(customer.predicted_probability, 2),
                        }}
                      />
                    </div>
                  </td>
                  <td>
                    <span
                      className={`decile-chip ${customer.score_decile >= 8 ? "high" : customer.score_decile <= 3 ? "low" : ""}`}
                    >
                      Decile {customer.score_decile}
                    </span>
                  </td>
                  <td>
                    <span className="activity-value">
                      {customer.dna.activity == null
                        ? "N/A"
                        : `${decimal(customer.dna.activity, 0)}th`}
                    </span>
                    <div className="tiny-meter">
                      <div
                        style={{
                          width: `${Math.max(0, Math.min(100, customer.dna.activity ?? 0))}%`,
                        }}
                      />
                    </div>
                  </td>
                  <td className="table-action">
                    <button
                      className="row-arrow"
                      aria-label={`View customer ${customer.household_key}`}
                      onClick={() => onPick(customer.household_key)}
                    >
                      <ArrowRight size={18} />
                    </button>
                  </td>
                </tr>
              ))}
              {!busy && !error && !result?.items.length && (
                <tr>
                  <td colSpan={5}>
                    <div className="empty-cell">
                      No households match this search. Try a different ID.
                    </div>
                  </td>
                </tr>
              )}
              {busy && (
                <tr>
                  <td colSpan={5}>
                    <div className="loading-block">
                      <span className="spinner" />
                      Loading customer records…
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="directory-footer">
          <span>
            {result && total
              ? `Showing ${offset + 1}–${Math.min(offset + LIMIT, total)} of ${decimal(total, 0)}`
              : "No records on this page"}
          </span>
          <div className="pagination">
            <button
              aria-label="Previous page"
              disabled={offset === 0 || busy}
              onClick={() => setOffset(Math.max(0, offset - LIMIT))}
            >
              <ChevronLeft size={18} />
            </button>
            <span>
              Page {Math.floor(offset / LIMIT) + 1} /{" "}
              {Math.max(1, Math.ceil(total / LIMIT))}
            </span>
            <button
              aria-label="Next page"
              disabled={busy || offset + LIMIT >= total}
              onClick={() => setOffset(offset + LIMIT)}
            >
              <ChevronRight size={18} />
            </button>
          </div>
        </div>
      </section>
      <p className="footnote">
        Predictions are retrospective model outputs from a fixed research
        dataset. High propensity does not imply campaign uplift.
      </p>
    </div>
  );
}
