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
