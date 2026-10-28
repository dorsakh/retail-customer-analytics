import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  CircleHelp,
  FlaskConical,
  Info,
  Search,
  ShieldAlert,
  TrendingDown,
  Users,
  X,
} from "lucide-react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import type {
  RetentionCustomer,
  RetentionDirectory,
  RetentionOverview,
  RetentionResearch,
} from "../types";

const SEGMENTS = [
  { value: "all", name: "All households" },
  { value: "at_risk", name: "At risk" },
  { value: "active", name: "Active" },
  { value: "inactive", name: "Inactive" },
  { value: "dormant", name: "Dormant" },
  { value: "limited_history", name: "Limited history" },
] as const;

const percent = (value: number | null | undefined, digits = 1) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : `${(value * 100).toFixed(digits)}%`;
const number = (value: number | null | undefined, digits = 1) =>
  value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
const cash = (value: number) =>
  new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(value);

function CustomerDetail({
  customer,
  horizonDays,
  close,
}: {
  customer: RetentionCustomer;
  horizonDays: number;
  close: () => void;
}) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const segmentReason =
    customer.segment === "dormant"
      ? "No recorded basket in at least 90 days. This is a lifecycle rule, not a model prediction."
      : customer.segment === "inactive"
        ? "The last basket was 31–89 days ago. This household belongs to the reactivation cohort."
        : customer.segment === "limited_history"
          ? "Fewer than three baskets in the past 90 days. There is not enough repeat-shopping history to assign a lapse score."
          : customer.segment === "at_risk"
            ? "An active repeat shopper ranked within the highest 20% of predicted lapse risk. This is a model-based prioritization flag."
            : "An active repeat shopper outside the highest-risk 20%. The model still estimates its future lapse probability.";

  const businessAction =
    customer.segment === "at_risk"
      ? "Review this household for a retention experiment or personalized follow-up. Randomized no-offer controls are needed before claiming an offer is profitable."
      : customer.segment === "active"
        ? "Continue routine engagement. Its predicted lapse risk is lower than the currently prioritized cohort."
        : customer.segment === "limited_history"
          ? "Keep this household visible and collect more shopping history before using the lapse model."
          : "Consider a separate reactivation workflow. The active-shopper lapse model does not estimate a probability for this segment.";

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
      if (event.key === "Tab") {
        event.preventDefault();
        closeButton.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
      previousFocus?.focus();
    };
  }, [close]);

  return (
    <div
      className="drawer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <aside
        className="customer-drawer retention-customer-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="retention-drawer-title"
      >
        <div className="drawer-topbar">
          <div className="eyebrow">
            RETENTION PROFILE · DAY {customer.as_of_day}
          </div>
          <button
            type="button"
            className="icon-button"
            ref={closeButton}
            onClick={close}
            aria-label="Close retention profile"
          >
            <X size={19} />
          </button>
        </div>
        <div className="drawer-scroll">
          <div className="retention-detail">
            <div className="retention-detail-header">
              <div>
                <div className="eyebrow">HOUSEHOLD SNAPSHOT</div>
                <h2 id="retention-drawer-title">
                  Household #{customer.household_key}
                </h2>
              </div>
              <span className={`retention-segment ${customer.segment}`}>
                {customer.segment.replaceAll("_", " ")}
              </span>
            </div>
            <div className="retention-risk-hero">
              <span>PREDICTED NO PURCHASE IN NEXT {horizonDays} DAYS</span>
              <strong>{percent(customer.lapse_probability)}</strong>
              <small>
                {customer.lapse_probability === null
                  ? "Not scored: outside the active repeat-shopper cohort"
                  : `Risk rank: #${customer.risk_rank} among eligible shoppers`}
              </small>
            </div>
            <div className="retention-detail-grid">
              <div>
                <span>Days since purchase</span>
                <strong>{customer.recency_days}</strong>
              </div>
              <div>
                <span>90-day baskets</span>
                <strong>{customer.baskets_90d}</strong>
              </div>
              <div>
                <span>90-day sales</span>
                <strong>{cash(customer.sales_90d ?? 0)}</strong>
              </div>
              <div>
                <span>Typical visit interval</span>
                <strong>{number(customer.typical_visit_gap_90d)} days</strong>
              </div>
              <div>
                <span>Gap / typical interval</span>
                <strong>{number(customer.overdue_ratio)}×</strong>
              </div>
            </div>
            <div className="retention-decision-note">
              <h3>Why this segment?</h3>
              <p>{segmentReason}</p>
              <h3>What can the business do?</h3>
              <p>{businessAction}</p>
            </div>
            <p className="retention-footnote">
              A lapse score is a probability of *not buying*, based on
              historical behavior. It is not a causal prediction of coupon
              responsiveness or profit.
            </p>
          </div>
        </div>
      </aside>
    </div>
  );
}

export default function Retention() {
  const [overview, setOverview] = useState<RetentionOverview | null>(null);
  const [research, setResearch] = useState<RetentionResearch | null>(null);
  const [directory, setDirectory] = useState<RetentionDirectory | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [segment, setSegment] = useState("all");
  const [sort, setSort] = useState("risk");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<RetentionCustomer | null>(null);
  const closeCustomer = useCallback(() => setSelected(null), []);
  const [assumedUplift, setAssumedUplift] = useState(0.05);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api.retentionOverview(controller.signal),
      api.retentionResearch(controller.signal),
    ])
      .then(([o, r]) => {
        setOverview(o);
        setResearch(r);
        setError("");
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!overview) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api
        .retentionDirectory(
          { q: search, segment, sort, limit: 16, offset: page * 16 },
          controller.signal,
        )
        .then(setDirectory)
        .catch((reason: Error) => {
          if (!controller.signal.aborted) setError(reason.message);
        });
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [overview, search, segment, sort, page]);

  const scenarios = useMemo(
    () =>
      research?.scenarios.filter(
        (row) =>
          Math.abs(row.assumed_incremental_response - assumedUplift) < 1e-8,
      ) ?? [],
    [research, assumedUplift],
  );
  const atRisk =
    overview?.segments.find((row) => row.segment === "at_risk")?.households ??
    0;
  const dormant =
    overview?.segments.find((row) => row.segment === "dormant")?.households ??
    0;
  const selectedPerformance = research?.holdout.find(
    (row) => row.model === research.decision.selected_model,
  );

  if (!overview || !research) {
    return (
      <div className="page-content">
        <div className="page-heading">
          <div className="eyebrow">
            <ShieldAlert size={15} /> RETENTION INTELLIGENCE
          </div>
          <h1>
            Find the customers <em>slipping away.</em>
          </h1>
          <p>
            Time-aware purchase patterns, customer lifecycle coverage, and
            retention decisions.
          </p>
        </div>
        <div className="retention-setup">
          <FlaskConical size={29} />
          <h2>
            {error
              ? "Retention analysis isn't ready yet"
              : "Loading retention research…"}
          </h2>
          <p>
            {error || "Reading the model results and current household roster."}
          </p>
          {error && (
            <>
              <p>
                The existing 7-day purchase model and dashboard are unchanged.
                To generate this separate v2 analysis, run:
              </p>
              <code>
                psql -d retail_analytics -v ON_ERROR_STOP=1 -f
                sql/marts/retention_features.sql
              </code>
              <code>
                psql -d retail_analytics -v ON_ERROR_STOP=1 -f
                sql/schema/retention.sql
              </code>
              <code>
                python -m retail_analytics.retention run --horizon auto --day
                711
              </code>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="page-content retention-page">
      <div className="retention-hero">
        <div className="eyebrow">
          <ShieldAlert size={15} /> RETENTION INTELLIGENCE · V2
        </div>
        <h1>
          Catch the change <em>before the customer goes quiet.</em>
        </h1>
        <p>
          Identify returning shoppers whose purchase rhythm may be breaking.
          Keep the full household roster visible, with honest historical
          evaluation and explicit campaign assumptions.
        </p>
        <div className="hero-tags">
          <span>Day {overview.as_of_day}</span>
          <span>{overview.horizon_days}-day lapse window</span>
          <span>{research.decision.selected_model}</span>
          <span>Observed behavior · No causal claims</span>
        </div>
      </div>

      <div className="metric-grid retention-metrics">
        <div className="metric-tile">
          <Users className="retention-icon" size={22} />
          <span>Known households</span>
          <strong>{overview.total_known_households.toLocaleString()}</strong>
          <small>All previously observed shoppers</small>
        </div>
        <div className="metric-tile">
          <ShieldAlert className="retention-icon" size={22} />
          <span>Flagged for review</span>
          <strong>{atRisk.toLocaleString()}</strong>
          <small>Highest-risk 20% of eligible shoppers</small>
        </div>
        <div className="metric-tile">
          <Activity className="retention-icon" size={22} />
          <span>Dormant households</span>
          <strong>{dormant.toLocaleString()}</strong>
          <small>Still included, not assigned model risk</small>
        </div>
        <div className="metric-tile">
          <TrendingDown className="retention-icon" size={22} />
          <span>Holdout precision @ 20%</span>
          <strong>{percent(selectedPerformance?.precision_at_capacity)}</strong>
          <small>Observed lapse events, not conversions</small>
        </div>
      </div>

      <section className="retention-panel">
        <div className="section-head">
          <div>
            <h2>Customer lifecycle</h2>
            <p>
              Every known household is searchable. Risk is scored only for
              active repeat buyers.
            </p>
          </div>
        </div>
        <p className="retention-operational-note">
          <strong>Business decision:</strong> identify active repeat customers
          most likely to pause purchasing, prioritize a review queue, and
          evaluate outreach with a randomized holdout. A higher lapse risk does
          not automatically mean a customer is more likely to respond to an
          offer.
        </p>
        <div className="retention-filters">
          <label className="retention-search">
            <Search size={18} />
            <input
              aria-label="Search retention household"
              placeholder="Find household ID…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(0);
              }}
            />
          </label>
          <select
            aria-label="Sort retention customers"
            value={sort}
            onChange={(e) => {
              setSort(e.target.value);
              setPage(0);
            }}
          >
            <option value="risk">Highest risk first</option>
            <option value="recency">Longest inactivity</option>
            <option value="household">Household ID</option>
          </select>
        </div>
        <div className="retention-tabs" aria-label="Lifecycle segments">
          {SEGMENTS.map((option) => (
            <button
              key={option.value}
              className={segment === option.value ? "selected" : ""}
              onClick={() => {
                setSegment(option.value);
                setPage(0);
                setSelected(null);
              }}
            >
              {option.name}
            </button>
          ))}
        </div>
        <div className="table-scroll">
          <table className="retention-table">
            <thead>
              <tr>
                <th>Household</th>
                <th>Segment</th>
                <th>Lapse risk</th>
                <th>Days since visit</th>
                <th>90d baskets</th>
                <th>Usual gap</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {directory?.items.map((item) => (
                <tr key={item.household_key}>
                  <td className="retention-customer">#{item.household_key}</td>
                  <td>
                    <span className={`retention-segment ${item.segment}`}>
                      {item.segment.replaceAll("_", " ")}
                    </span>
                  </td>
                  <td>
                    {item.lapse_probability == null ? (
                      "Not scored"
                    ) : (
                      <>
                        <div className="retention-score-bar">
                          <span
                            style={{
                              width: `${item.lapse_probability * 100}%`,
                            }}
                          />
                        </div>
                        <b>{percent(item.lapse_probability)}</b>
                      </>
                    )}
                  </td>
                  <td>{item.recency_days}</td>
                  <td>{item.baskets_90d}</td>
                  <td>{number(item.typical_visit_gap_90d)} days</td>
                  <td>
                    <button
                      className="retention-inspect"
                      aria-label={`Inspect retention household ${item.household_key}`}
                      onClick={() => setSelected(item)}
                    >
                      Inspect <ArrowRight size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {directory?.items.length === 0 && (
          <p className="retention-empty">No households match these filters.</p>
        )}
        <div className="retention-pagination">
          <span>{directory?.total.toLocaleString() ?? 0} records</span>
          <div>
            <button
              disabled={page === 0}
              onClick={() => setPage((v) => v - 1)}
              aria-label="Previous retention page"
            >
              <ArrowLeft size={17} />
            </button>
            <span>Page {page + 1}</span>
            <button
              disabled={!directory || (page + 1) * 16 >= directory.total}
              onClick={() => setPage((v) => v + 1)}
              aria-label="Next retention page"
            >
              <ArrowRight size={17} />
            </button>
          </div>
        </div>
      </section>

      {selected && (
        <CustomerDetail
          customer={selected}
          horizonDays={overview.horizon_days}
          close={closeCustomer}
        />
      )}

      <section className="retention-panel">
        <div className="section-head">
          <div>
            <h2>Evidence, not intuition</h2>
            <p>
              Horizon and model selection used validation periods; all final
              metrics come from later untouched observation days.
            </p>
          </div>
        </div>
        <div className="retention-research-grid">
          <div className="retention-research-card">
            <div className="eyebrow">HORIZON STUDY · VALIDATION</div>
            <h3>How long is too long?</h3>
            <p>
              Compare three operational definitions on the same active cohort.
            </p>
            <div className="retention-horizons">
              {research.horizons.map((row) => (
                <div
                  key={row.horizon_days}
                  className={
                    row.horizon_days === overview.horizon_days ? "chosen" : ""
                  }
                >
                  <strong>{row.horizon_days} days</strong>
                  <span>{percent(row.lapse_rate)} lapse rate</span>
                  <b>{number(row.lift_at_capacity, 2)}× lift</b>
                </div>
              ))}
            </div>
          </div>
          <div className="retention-research-card">
            <div className="eyebrow">UNSEEN HOLDOUT</div>
            <h3>Does complexity pay?</h3>
            <p>
              Same dates and household cohort; the LR benchmark stays in view.
            </p>
            <div className="retention-benchmark">
              {research.holdout.map((row) => (
                <div key={row.model}>
                  <span>{row.model}</span>
                  <strong>{percent(row.precision_at_capacity)}</strong>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="retention-research-grid">
          <div className="retention-research-card">
            <div className="eyebrow">FEATURE ABLATION · VALIDATION</div>
            <h3>Which signals earn their place?</h3>
            <div className="retention-benchmark">
              {research.ablation.map((row) => (
                <div key={row.model}>
                  <span>
                    {row.model}
                    <small>{row.n_features} encoded inputs</small>
                  </span>
                  <strong>{percent(row.precision_at_capacity)}</strong>
                </div>
              ))}
            </div>
          </div>
          <div className="retention-research-card">
            <div className="eyebrow">
              {research.replay.length > 3
                ? "DAILY HISTORICAL REPLAY"
                : "HOLDOUT · THREE DATES"}
            </div>
            <h3>
              {research.replay.length > 3
                ? "Risk across daily batches"
                : "Risk across holdout dates"}
            </h3>
            <p>
              {research.replay.length > 3
                ? "Frozen development-only model, evaluated on daily historical snapshots."
                : "Frozen development-only model, evaluated at three fixed dates with matured outcomes. Not a daily replay."}
            </p>
            <div className="retention-chart">
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={research.replay}>
                  <CartesianGrid stroke="#e9eeeb" strokeDasharray="3 3" />
                  <XAxis dataKey="as_of_day" tickLine={false} />
                  <YAxis
                    domain={[0, 1]}
                    tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                  />
                  <Tooltip formatter={(v) => percent(Number(v))} />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="mean_predicted_risk"
                    name="Predicted lapse"
                    stroke="#368f76"
                    strokeWidth={3}
                    dot
                  />
                  <Line
                    type="monotone"
                    dataKey="observed_lapse_rate"
                    name="Observed lapse"
                    stroke="#b57445"
                    strokeWidth={3}
                    dot
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </section>

      <section className="retention-panel">
        <div className="section-head">
          <div>
            <h2>What would an offer have to achieve?</h2>
            <p>
              Break-even and capacity sensitivity under stated assumptions—not a
              measured incremental return.
            </p>
          </div>
          <CircleHelp size={23} color="#669084" />
        </div>
        <div className="retention-economics-note">
          <Info size={18} />
          <span>
            This dataset does not identify each customer's causal coupon
            response. Every profit value below is hypothetical, not a claim that
            outreach generates revenue.
          </span>
        </div>
        <div className="retention-scenario-control">
          <label htmlFor="uplift-scenario">
            Assumed incremental purchase response
          </label>
          <select
            id="uplift-scenario"
            value={assumedUplift}
            onChange={(e) => setAssumedUplift(Number(e.target.value))}
          >
            {[0.01, 0.03, 0.05, 0.1, 0.15, 0.2].map((v) => (
              <option key={v} value={v}>
                {percent(v, 0)}
              </option>
            ))}
          </select>
          <span>
            Break-even:{" "}
            {percent(scenarios[0]?.break_even_incremental_response, 1)}
          </span>
        </div>
        <div className="retention-profit-chart">
          <ResponsiveContainer width="100%" height={235}>
            <LineChart
              data={scenarios.map((row) => ({
                ...row,
                capacity_label: `${Math.round(row.capacity * 100)}%`,
              }))}
            >
              <CartesianGrid stroke="#e8eee9" strokeDasharray="3 3" />
              <XAxis dataKey="capacity_label" />
              <YAxis tickFormatter={(v: number) => cash(v)} />
              <Tooltip formatter={(v) => cash(Number(v))} />
              <Line
                dataKey="hypothetical_net_value"
                name="Hypothetical net value"
                stroke="#398a73"
                strokeWidth={3}
                dot
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="retention-scenario-grid">
          {scenarios.map((row) => (
            <div key={row.capacity}>
              <small>
                {percent(row.capacity, 0)} capacity ·{" "}
                {row.contacts.toLocaleString()} contacts
              </small>
              <strong
                className={
                  row.hypothetical_net_value >= 0 ? "positive" : "negative"
                }
              >
                {cash(row.hypothetical_net_value)}
              </strong>
            </div>
          ))}
        </div>
        <p className="retention-footnote">
          Assumed constant response for every contacted household. Therefore
          this exercise cannot establish an optimal shortlist size or prove that
          highest-risk customers are the most persuadable.
        </p>
      </section>
    </div>
  );
}
