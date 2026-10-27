import type { Features, PurchaseEvent } from "./types";

export const percent = (number: number | null | undefined, decimals = 1) =>
  number == null || !Number.isFinite(number)
    ? "—"
    : `${(number * 100).toFixed(decimals)}%`;

export const decimal = (number: number | null | undefined, digits = 1) =>
  number == null || !Number.isFinite(number)
    ? "—"
    : number.toLocaleString("en-US", { maximumFractionDigits: digits });

export const currency = (number: number | null | undefined) =>
  number == null || !Number.isFinite(number)
    ? "—"
    : `$${number.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

export const label = (name: string) =>
  name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase())
    .replace(/\b90d\b/g, "90d")
    .replace(/\b30d\b/g, "30d");

export const featureSections: { heading: string; names: string[] }[] = [
  {
    heading: "Visits & frequency",
    names: [
      "recency_days",
      "baskets_90d",
      "baskets_30d",
      "baskets_previous_30d",
      "avg_days_between_visits_90d",
      "visit_interval_volatility_90d",
    ],
  },
  {
    heading: "Spend & basket composition",
    names: [
      "sales_90d",
      "sales_30d",
      "sales_previous_30d",
      "sales_growth_30d",
      "avg_basket_value_90d",
      "basket_value_volatility_90d",
      "avg_product_diversity_90d",
    ],
  },
  {
    heading: "Store & promotion",
    names: ["distinct_stores_90d", "discount_share_90d"],
  },
];

export const dnaSignals = [
  { key: "activity", title: "Shopping activity", hint: "Basket frequency" },
  {
    key: "regularity",
    title: "Visit consistency",
    hint: "Regularity of visits",
  },
  { key: "spending", title: "Spending power", hint: "90-day sales" },
  { key: "momentum", title: "Purchase momentum", hint: "Recent sales growth" },
  {
    key: "discount_reliance",
    title: "Discount affinity",
    hint: "Discount share",
  },
] as const;

export function weeklyHistory(events: PurchaseEvent[]) {
  const bins = Array.from({ length: 13 }, (_, index) => ({
    week: index === 12 ? "Now" : `-${12 - index}w`,
    sales: 0,
    baskets: 0,
  }));
  for (const event of events) {
    if (
      !Number.isFinite(event.days_ago) ||
      event.days_ago < 0 ||
      event.days_ago >= 90
    )
      continue;
    const index = Math.min(12, Math.floor((89 - event.days_ago) / 7));
    bins[index].sales += Number(event.sales) || 0;
    bins[index].baskets += Number(event.baskets) || 0;
  }
  return bins;
}

export function numericFeatures(features: Features) {
  return Object.entries(features).filter(([, value]) => value != null).length;
}
