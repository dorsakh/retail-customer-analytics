export type Features = Record<string, number | null>;

export type DNA = {
  activity: number | null;
  regularity: number | null;
  spending: number | null;
  momentum: number | null;
  discount_reliance: number | null;
};

export type PurchaseEvent = {
  days_ago: number;
  sales: number;
  baskets: number;
};

export type DirectoryCustomer = {
  household_key: string;
  predicted_probability: number;
  propensity_rank: number;
  score_decile: number;
  dna: DNA;
};

export type DirectoryResponse = {
  as_of_day: number;
  total: number;
  limit: number;
  offset: number;
  items: DirectoryCustomer[];
};

export type CustomerProfile = DirectoryCustomer & {
  as_of_day: number;
  model_version: string;
  features: Features;
  purchase_history: PurchaseEvent[];
  live_model_probability: number;
};

export type ParadoxDifference = {
  feature: string;
  raw_score_difference: number;
  higher_customer_value: number | null;
  lower_customer_value: number | null;
};

export type ParadoxPair = {
  high_household: string;
  low_household: string;
  high_probability: number;
  low_probability: number;
  probability_gap: number;
  recency_days: number;
  high_baskets_90d: number;
  low_baskets_90d: number;
  top_differences: ParadoxDifference[];
};

export type GameCase = {
  household_key: string;
  as_of_day: number;
  features: Features;
  purchase_history: PurchaseEvent[];
};

export type GameReveal = {
  repurchased_7d: boolean;
  your_probability: number;
  model_probability: number;
  your_brier: number;
  model_brier: number;
  beat_model: boolean;
  baseline_rank: number;
  note: string;
};

export type FeatureDrift = {
  feature: string;
  psi: number;
  reference_missing_rate: number;
  current_missing_rate: number;
  warning: boolean;
};

export type MonitoringReport = {
  as_of_day: number;
  model_version: string;
  checked_at: string;
  household_count: number;
  drift_status: "ok" | "watch";
  prediction_drift: { psi: number; warning: boolean };
  feature_drift: FeatureDrift[];
  alerts: { type: string; feature?: string }[];
  label_status: string;
  outcome_metrics: Record<string, number> | null;
};

export type PipelineRun = {
  run_id: string;
  as_of_day: number;
  status: string;
  model_version: string;
  input_rows: number | null;
  scored_rows: number | null;
  started_at: string;
  finished_at: string | null;
};

export type RetentionCustomer = {
  household_key: string;
  as_of_day: number;
  horizon_days: number;
  segment: "at_risk" | "active" | "inactive" | "dormant" | "limited_history";
  lapse_probability: number | null;
  risk_rank: number | null;
  recency_days: number;
  baskets_90d: number;
  typical_visit_gap_90d: number | null;
  overdue_ratio: number | null;
  sales_90d: number | null;
};

export type RetentionOverview = {
  as_of_day: number;
  model_version: string;
  horizon_days: number;
  total_known_households: number;
  segments: {
    segment: RetentionCustomer["segment"];
    households: number;
    mean_lapse_probability: number | null;
  }[];
  interpretation: string;
};

export type RetentionDirectory = {
  total: number;
  offset: number;
  limit: number;
  items: RetentionCustomer[];
};

export type RetentionMetric = {
  model: string;
  roc_auc: number | null;
  avg_precision: number | null;
  brier: number | null;
  lapse_rate: number;
  precision_at_capacity: number;
  recall_at_capacity: number;
  lift_at_capacity: number;
};

export type RetentionResearch = {
  decision: {
    selected_horizon_days: number;
    selected_model: string;
    horizon_selection: string;
  };
  horizons: (RetentionMetric & { horizon_days: number })[];
  holdout: RetentionMetric[];
  bootstrap: {
    comparison: string;
    precision_gap_pp: number;
    ci_low_pp: number;
    ci_high_pp: number;
  }[];
  ablation: (RetentionMetric & { model: string; n_features: number })[];
  scenarios: {
    capacity: number;
    contacts: number;
    assumed_incremental_response: number;
    break_even_incremental_response: number;
    hypothetical_net_value: number;
  }[];
  replay: {
    as_of_day: number;
    observed_lapse_rate: number;
    mean_predicted_risk: number;
    prediction_psi_vs_validation: number | null;
  }[];
  disclaimer: string;
};
