import { useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock3,
  DatabaseZap,
  RefreshCw,
} from "lucide-react";
import { api } from "../api";
import type { MonitoringReport, PipelineRun } from "../types";
import { decimal, label } from "../utils";

export default function Health() {
  const [report, setReport] = useState<MonitoringReport | null>(null);
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [token, setToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    Promise.allSettled([
      api.monitoring(controller.signal),
      api.runs(controller.signal),
    ])
      .then(([monitoring, pipeline]) => {
        if (controller.signal.aborted) return;
        if (monitoring.status === "fulfilled") setReport(monitoring.value);
        else
          setError(
            monitoring.reason?.message || "Monitoring data unavailable.",
          );
        if (pipeline.status === "fulfilled") setRuns(pipeline.value);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [token]);

  const flagged =
    report?.feature_drift.filter((feature) => feature.warning) || [];
  const top = [...(report?.feature_drift || [])]
    .sort((a, b) => b.psi - a.psi)
    .slice(0, 6);

  return (
    <div className="page-content">
      <div className="page-heading split-heading">
        <div>
          <div className="eyebrow">
            <span className="eyebrow-dot" /> OPERATIONS / 04
          </div>
          <h1>
            Model <em>Pulse.</em>
          </h1>
          <p>
            Descriptive monitoring and the actual execution history of the
            scoring pipeline.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={loading}
          onClick={() => setToken((value) => value + 1)}
        >
          <RefreshCw size={17} /> Refresh
        </button>
      </div>
      {loading && (
        <div className="loading-card">
          <span className="spinner" /> Reading monitoring reports…
        </div>
      )}
      {error && (
        <div className="inline-message error-box" role="status">
          {error} Run the monitoring job to create the first report.
        </div>
      )}
      {report && (
        <>
          <div className="health-metric-grid">
            <div className="health-tile">
              <span>
                <Activity size={18} /> Drift status
              </span>
              <strong
                className={
                  report.drift_status === "ok" ? "health-good" : "health-watch"
                }
              >
                {report.drift_status === "ok"
                  ? "Within threshold"
                  : "Review required"}
              </strong>
              <small>{flagged.length} of 15 feature alerts</small>
            </div>
            <div className="health-tile">
              <span>
                <DatabaseZap size={18} /> Prediction PSI
              </span>
              <strong>{decimal(report.prediction_drift.psi, 4)}</strong>
              <small>Review threshold: 0.20</small>
            </div>
            <div className="health-tile">
              <span>
                <Clock3 size={18} /> Seven-day labels
              </span>
              <strong className="pending-label">
                {report.label_status === "pending"
                  ? "Pending"
                  : report.label_status.replaceAll("_", " ")}
              </strong>
              <small>
                {report.label_status === "pending"
                  ? "Future transactions not yet available"
                  : "Latest outcome status"}
              </small>
            </div>
          </div>
          <section className="health-card">
            <div className="section-head">
              <div>
                <div className="overline">DATA QUALITY MONITORING</div>
                <h2>Largest feature distribution shifts</h2>
                <p>
                  PSI against training-period snapshots; not a direct accuracy
                  measure.
                </p>
              </div>
              <span className="tiny-pill">Day {report.as_of_day}</span>
            </div>
            <div className="drift-list">
              {top.map((feature) => (
                <div className="drift-row" key={feature.feature}>
                  <span>{label(feature.feature)}</span>
                  <div className="drift-bar">
                    <div
                      className={feature.warning ? "warning" : ""}
                      style={{
                        width: `${Math.max(0, Math.min(100, (100 * feature.psi) / 0.2))}%`,
                      }}
                    />
                  </div>
                  <strong>{decimal(feature.psi, 4)}</strong>
                </div>
              ))}
            </div>
            {report.drift_status === "ok" ? (
              <div className="health-note">
                <CheckCircle2 size={17} /> No feature or prediction alerts
                triggered in this report.
              </div>
            ) : (
              <div className="health-note warn">
                <AlertCircle size={17} /> Check monitored features and source
                data before making decisions.
              </div>
            )}
          </section>
        </>
      )}
      <section className="health-card">
        <div className="section-head">
          <div>
            <div className="overline">BATCH AUTOMATION</div>
            <h2>Recent scoring runs</h2>
            <p>Audited in PostgreSQL with idempotent execution.</p>
          </div>
          <span className="tiny-pill">Latest 8</span>
        </div>
        {!runs.length && !loading && (
          <div className="empty-state">
            No pipeline run history is available yet.
          </div>
        )}
        {!!runs.length && (
          <div className="run-table-wrap">
            <table className="run-table">
              <thead>
                <tr>
                  <th>RUN</th>
                  <th>DAY</th>
                  <th>STATUS</th>
                  <th>SCORED</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.run_id}>
                    <td>{run.run_id.slice(0, 8)}…</td>
                    <td>{run.as_of_day}</td>
                    <td>
                      <span className={`run-chip ${run.status}`}>
                        {run.status}
                      </span>
                    </td>
                    <td>{decimal(run.scored_rows, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <p className="footnote">
        Monitoring reflects a fixed historical dataset and runs when its local
        Docker or Python host is running. A pending outcome is not a failed
        prediction.
      </p>
    </div>
  );
}
