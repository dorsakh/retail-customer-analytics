import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { api } from "../api";

vi.mock("../api", () => ({
  api: {
    directory: vi.fn(),
    customer: vi.fn(),
    paradoxes: vi.fn(),
    newGame: vi.fn(),
    guess: vi.fn(),
    monitoring: vi.fn(),
    runs: vi.fn(),
    retentionOverview: vi.fn(),
    retentionDirectory: vi.fn(),
    retentionResearch: vi.fn(),
  },
}));

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  BarChart: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  CartesianGrid: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  Bar: () => null,
  LineChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Line: () => null,
  Legend: () => null,
}));

const emptyDna = {
  activity: 68,
  regularity: 37,
  spending: 55,
  momentum: 40,
  discount_reliance: 19,
};
const features = {
  recency_days: 5,
  baskets_90d: 12,
  baskets_30d: 4,
  baskets_previous_30d: 3,
  avg_days_between_visits_90d: 9,
  visit_interval_volatility_90d: 2,
  sales_90d: 220,
  sales_30d: 89,
  sales_previous_30d: 78,
  sales_growth_30d: 0.1,
  avg_basket_value_90d: 18,
  basket_value_volatility_90d: 6,
  avg_product_diversity_90d: 7,
  distinct_stores_90d: 2,
  discount_share_90d: 0.23,
};

beforeEach(() => {
  vi.mocked(api.directory).mockResolvedValue({
    as_of_day: 711,
    total: 2326,
    limit: 16,
    offset: 0,
    items: [
      {
        household_key: "1907",
        propensity_rank: 1,
        predicted_probability: 0.9899,
        score_decile: 10,
        dna: emptyDna,
      },
    ],
  });
  vi.mocked(api.customer).mockImplementation(async (key) => ({
    household_key: key,
    as_of_day: 711,
    model_version: "v1",
    propensity_rank: 1,
    predicted_probability: 0.9899,
    live_model_probability: 0.9899,
    score_decile: 10,
    dna: emptyDna,
    features,
    purchase_history: [{ days_ago: 3, baskets: 1, sales: 22 }],
  }));
  vi.mocked(api.paradoxes).mockResolvedValue([
    {
      high_household: "1907",
      low_household: "41",
      high_probability: 0.85,
      low_probability: 0.22,
      probability_gap: 0.63,
      recency_days: 5,
      high_baskets_90d: 12,
      low_baskets_90d: 12,
      top_differences: [
        {
          feature: "sales_90d",
          raw_score_difference: 0.5,
          higher_customer_value: 220,
          lower_customer_value: 55,
        },
      ],
    },
  ]);
  vi.mocked(api.newGame).mockResolvedValue({
    household_key: "98",
    as_of_day: 690,
    features,
    purchase_history: [],
  });
  vi.mocked(api.guess).mockResolvedValue({
    repurchased_7d: true,
    your_probability: 0.72,
    model_probability: 0.45,
    your_brier: 0.0784,
    model_brier: 0.3025,
    beat_model: true,
    baseline_rank: 10,
    note: "Holdout",
  });
  vi.mocked(api.monitoring).mockResolvedValue({
    as_of_day: 711,
    model_version: "v1",
    checked_at: "",
    household_count: 2326,
    drift_status: "ok",
    prediction_drift: { psi: 0.0062, warning: false },
    feature_drift: [
      {
        feature: "sales_90d",
        psi: 0.02,
        warning: false,
        reference_missing_rate: 0,
        current_missing_rate: 0,
      },
    ],
    alerts: [],
    label_status: "pending",
    outcome_metrics: null,
  });
  vi.mocked(api.runs).mockResolvedValue([
    {
      run_id: "test-run-123",
      as_of_day: 711,
      status: "succeeded",
      model_version: "v1",
      scored_rows: 2326,
      input_rows: 2326,
      started_at: "",
      finished_at: "",
    },
  ]);
  vi.mocked(api.retentionOverview).mockResolvedValue({
    as_of_day: 711,
    model_version: "lapse_v2",
    horizon_days: 14,
    total_known_households: 2500,
    interpretation: "Not causal uplift",
    segments: [
      { segment: "at_risk", households: 300, mean_lapse_probability: 0.6 },
      { segment: "dormant", households: 174, mean_lapse_probability: null },
    ],
  });
  vi.mocked(api.retentionDirectory).mockResolvedValue({
    total: 2500, offset: 0, limit: 16,
    items: [{
      household_key: "15", as_of_day: 711, horizon_days: 14,
      segment: "at_risk", lapse_probability: 0.65, risk_rank: 1,
      recency_days: 11, baskets_90d: 14,
      typical_visit_gap_90d: 5, overdue_ratio: 2.2, sales_90d: 460,
    }],
  });
  const metric = {
    model: "LightGBM", roc_auc: 0.7, avg_precision: 0.5,
    brier: 0.2, lapse_rate: 0.28,
    precision_at_capacity: 0.52, recall_at_capacity: 0.43,
    lift_at_capacity: 1.86,
  };
  vi.mocked(api.retentionResearch).mockResolvedValue({
    decision: {
      selected_horizon_days: 14,
      selected_model: "LightGBM",
      horizon_selection: "validation",
    },
    horizons: [{ ...metric, horizon_days: 7 }, { ...metric, horizon_days: 14 }],
    holdout: [metric, { ...metric, model: "Logistic regression", precision_at_capacity: .46 }],
    bootstrap: [],
    ablation: [{ ...metric, n_features: 25 }],
    scenarios: [{ capacity: 0.20, contacts: 300,
      assumed_incremental_response: .05,
      break_even_incremental_response: .13,
      hypothetical_net_value: -375 }],
    replay: [{ as_of_day: 600, observed_lapse_rate: .28,
      mean_predicted_risk: .27, prediction_psi_vs_validation: .01 }],
    disclaimer: "Not causal ROI",
  });
});

describe("Behind the Basket", () => {
  it("keeps the complete cohort in the Retention Lab and opens risk details in place", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Retention Lab/ }));
    expect(await screen.findByText("2,500")).toBeInTheDocument();
    expect(screen.getByText("Dormant households")).toBeInTheDocument();
    const inspect = await screen.findByRole("button", { name: "Inspect retention household 15" });
    await user.click(inspect);
    const profile = screen.getByRole("dialog", { name: "Household #15" });
    expect(within(profile).getByText("Why this segment?")).toBeInTheDocument();
    expect(within(profile).getByText("What can the business do?")).toBeInTheDocument();
    expect(within(profile).getByText(/predicted no purchase in next 14 days/i)).toBeInTheDocument();
    expect(screen.getByText("What would an offer have to achieve?")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Household #15" })).not.toBeInTheDocument();
    expect(inspect).toHaveFocus();
  });
  it("searches the full directory and opens a detailed customer drawer without navigation", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText("#1907")).toBeInTheDocument();
    expect(screen.getByText(/2,326 records/)).toBeInTheDocument();
    await user.type(
      screen.getByRole("textbox", { name: "Search household ID" }),
      "190",
    );
    await waitFor(() =>
      expect(api.directory).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "190" }),
        expect.any(AbortSignal),
      ),
    );
    await user.click(
      screen.getByRole("button", { name: "View customer 1907" }),
    );
    const dialog = await screen.findByRole("dialog", { name: "#1907" });
    expect(await within(dialog).findByText("Shopping DNA")).toBeInTheDocument();
    expect(
      within(dialog).getByText("All 15 behavioral signals"),
    ).toBeInTheDocument();
    expect(screen.getByText("Customer directory")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("inspects paradox households in place, keeping comparisons on screen", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(
      screen.getByRole("button", { name: /Behavioral Paradox/ }),
    );
    expect(await screen.findByText("Household #41")).toBeInTheDocument();
    expect(screen.getByText("Features behind the gap")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Hide comparison details" }),
    );
    expect(
      screen.queryByText("Features behind the gap"),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Why does the model disagree?" }),
    );
    await user.click(
      screen.getAllByRole("button", { name: /Open full profile/ })[1],
    );
    expect(
      await screen.findByRole("dialog", { name: "#41" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Features behind the gap")).toBeInTheDocument();
  });

  it("reveals historical game outcomes only after a prediction", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Beat the Model/ }));
    expect(await screen.findByText("Meet household")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider"), { target: { value: "72" } });
    await user.click(
      screen.getByRole("button", { name: /Reveal the outcome/ }),
    );
    expect(await screen.findByText("They came back")).toBeInTheDocument();
    expect(
      screen.getByText(/You beat the model this round/),
    ).toBeInTheDocument();
    expect(api.guess).toHaveBeenCalledWith(690, "98", 0.72);
  });

  it("reads monitoring and audited batch status from API", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Model Pulse/ }));
    expect(await screen.findByText("Within threshold")).toBeInTheDocument();
    expect(screen.getByText("0.0062")).toBeInTheDocument();
    expect(screen.getByText("succeeded")).toBeInTheDocument();
  });
});
