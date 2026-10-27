import { useCallback, useEffect, useState } from "react";
import {
  ArrowRight,
  Check,
  CircleHelp,
  RotateCcw,
  Target,
  Trophy,
  Zap,
} from "lucide-react";
import { api } from "../api";
import type { GameCase, GameReveal } from "../types";
import { decimal, featureSections, label, percent } from "../utils";
import HistoryChart from "../components/HistoryChart";

export default function Challenge() {
  const [caseData, setCaseData] = useState<GameCase | null>(null);
  const [guess, setGuess] = useState(50);
  const [outcome, setOutcome] = useState<GameReveal | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [rounds, setRounds] = useState(0);
  const [wins, setWins] = useState(0);

  const loadCase = useCallback(async () => {
    setLoading(true);
    setError("");
    setOutcome(null);
    setGuess(50);
    setCaseData(null);
    try {
      setCaseData(await api.newGame());
    } catch (reason) {
      setError(String((reason as Error).message));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCase();
  }, [loadCase]);

  const submit = async () => {
    if (!caseData || submitting || outcome) return;
    setSubmitting(true);
    setError("");
    try {
      const revealed = await api.guess(
        caseData.as_of_day,
        caseData.household_key,
        guess / 100,
      );
      setOutcome(revealed);
      setRounds((value) => value + 1);
      if (revealed.beat_model) setWins((value) => value + 1);
    } catch (reason) {
      setError(String((reason as Error).message));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page-content">
      <div className="page-heading">
        <div className="eyebrow">
          <span className="eyebrow-dot" /> EXPERIMENT LAB / 03
        </div>
        <h1>
          Beat the <em>Model.</em>
        </h1>
        <p>
          You have 90 days of shopping history. Predict what happens next—and
          see if your judgment beats a trained classifier.
        </p>
      </div>
      <div className="game-scorebar">
        <div>
          <Trophy size={20} />
          <strong>{wins}</strong>
          <span>Model wins beaten</span>
        </div>
        <div>
          <Target size={20} />
          <strong>{rounds}</strong>
          <span>Rounds played</span>
        </div>
        <div className="game-score-note">
          <Zap size={18} />
          Each question comes from previously unseen holdout dates.
        </div>
      </div>

      {error && (
        <div className="error-box" role="alert">
          {error}{" "}
          <button className="text-link" onClick={() => void loadCase()}>
            Retry
          </button>
        </div>
      )}
      {loading && (
        <div className="loading-card">
          <span className="spinner" /> Preparing a historical shopping case…
        </div>
      )}

      {caseData && !loading && (
        <div className="challenge-grid">
          <section className="game-context-card">
            <div className="card-kicker">
              <span>CASE STUDY</span>
              <span className="tiny-pill">
                Holdout · Day {caseData.as_of_day}
              </span>
            </div>
            <h2>
              Meet household <span>#{caseData.household_key}</span>
            </h2>
            <p>
              Everything below was available before the seven-day outcome. No
              future shopping information is revealed yet.
            </p>
            <div className="case-stat-grid">
              <div>
                <span>90-day baskets</span>
                <strong>{decimal(caseData.features.baskets_90d, 0)}</strong>
              </div>
              <div>
                <span>Days since last visit</span>
                <strong>{decimal(caseData.features.recency_days, 0)}</strong>
              </div>
              <div>
                <span>30-day baskets</span>
                <strong>{decimal(caseData.features.baskets_30d, 0)}</strong>
              </div>
            </div>
            <div className="case-chart-title">
              <strong>Purchase activity</strong>
              <span>Past 90 days</span>
            </div>
            <HistoryChart events={caseData.purchase_history} height={210} />
            <details className="case-features">
              <summary>
                <CircleHelp size={17} />
                Inspect all 15 model inputs
              </summary>
              {featureSections.map((section) => (
                <div className="case-feature-section" key={section.heading}>
                  <h4>{section.heading}</h4>
                  <div className="case-feature-list">
                    {section.names.map((name) => (
                      <div key={name}>
                        <span>{label(name)}</span>
                        <strong>{decimal(caseData.features[name], 2)}</strong>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </details>
          </section>

          <section className="game-decision-card">
            <span className="overline">YOUR CALL</span>
            <h2>Will they come back?</h2>
            <p>
              Set your probability for a purchase within the next seven days.
            </p>
            <div className="guess-display">
              <strong>{guess}%</strong>
              <span>Your prediction</span>
            </div>
            <label className="range-field">
              <span>0% — unlikely</span>
              <span>100% — certain</span>
            </label>
            <input
              type="range"
              className="guess-slider"
              min={0}
              max={100}
              value={guess}
              style={{
                background: `linear-gradient(to right,#2d8f76 ${guess}%,#e4ebe6 ${guess}%)`,
              }}
              onChange={(event) => setGuess(Number(event.target.value))}
              disabled={Boolean(outcome) || submitting}
              aria-label="Your predicted seven-day repurchase probability"
            />
            {!outcome && (
              <button
                className="primary-button full-width"
                disabled={submitting}
                onClick={() => void submit()}
              >
                {submitting ? "Comparing predictions…" : "Reveal the outcome"}{" "}
                <ArrowRight size={18} />
              </button>
            )}

            {outcome && (
              <div className="game-outcome" aria-live="polite">
                <div
                  className={`outcome-stamp ${outcome.repurchased_7d ? "positive" : ""}`}
                >
                  <Check size={17} />
                  {outcome.repurchased_7d
                    ? "They came back"
                    : "No return recorded"}
                </div>
                <div className="outcome-summary">
                  <div>
                    <span>Your prediction</span>
                    <strong>{percent(outcome.your_probability, 0)}</strong>
                  </div>
                  <div>
                    <span>LightGBM</span>
                    <strong>{percent(outcome.model_probability, 0)}</strong>
                  </div>
                </div>
                <div className="brier-comparison">
                  <span>Brier loss · lower is better</span>
                  <div>
                    <strong>You: {decimal(outcome.your_brier, 4)}</strong>
                    <strong>Model: {decimal(outcome.model_brier, 4)}</strong>
                  </div>
                </div>
                <div className={`verdict ${outcome.beat_model ? "win" : ""}`}>
                  {outcome.beat_model ? (
                    <>
                      <Trophy size={18} /> You beat the model this round.
                    </>
                  ) : (
                    "The model had the lower prediction error."
                  )}
                </div>
                <button
                  className="primary-button full-width"
                  onClick={() => void loadCase()}
                >
                  Try another household <RotateCcw size={17} />
                </button>
              </div>
            )}
            <p className="game-caveat">
              The outcome is historical. The comparison uses a model trained
              before the holdout dates—not the later refitted production model.
            </p>
          </section>
        </div>
      )}
    </div>
  );
}
