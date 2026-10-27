import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PurchaseEvent } from "../types";
import { currency, weeklyHistory } from "../utils";

export default function HistoryChart({
  events,
  height = 210,
}: {
  events: PurchaseEvent[];
  height?: number;
}) {
  if (!events.length) {
    return (
      <div className="chart-empty">
        No purchases recorded in the last 90 days.
      </div>
    );
  }
  return (
    <div
      className="history-chart"
      style={{ height }}
      role="img"
      aria-label="Weekly purchase sales in the past 90 days"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={weeklyHistory(events)}
          margin={{ top: 8, right: 4, left: -18, bottom: 2 }}
        >
          <CartesianGrid
            vertical={false}
            stroke="#e5eae9"
            strokeDasharray="3 4"
          />
          <XAxis
            dataKey="week"
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#85918d", fontSize: 11 }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#85918d", fontSize: 11 }}
            width={42}
          />
          <Tooltip
            cursor={{ fill: "#eaf6ee" }}
            contentStyle={{
              border: "1px solid #e6ebe8",
              borderRadius: 12,
              boxShadow: "0 8px 24px #132e2312",
            }}
            formatter={(value) => [currency(Number(value)), "Sales"]}
          />
          <Bar
            dataKey="sales"
            fill="#2d8f76"
            radius={[5, 5, 0, 0]}
            maxBarSize={27}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
