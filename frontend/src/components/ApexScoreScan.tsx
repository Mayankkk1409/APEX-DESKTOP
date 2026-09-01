import { useState } from "react";
import { scoreTier } from "../lib/chartHighlight";
import type { ApexScoreLayer } from "../types";

function fmt(v: unknown, digits = 1): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number" && Number.isFinite(v)) return v.toFixed(digits);
  return String(v);
}

function compositeGaugeOffset(score: number | null): number {
  if (score === null || Number.isNaN(score)) return 126;
  const t = Math.max(0, Math.min(100, score)) / 100;
  return 126 * (1 - t);
}

function NarrativeBlock({
  paragraphs,
  narrative,
  interpretation,
  testId,
}: {
  paragraphs?: string[];
  narrative?: string;
  interpretation?: string;
  testId?: string;
}) {
  const blocks =
    paragraphs?.length
      ? paragraphs
      : narrative
        ? narrative.split(/\n\n+/).filter((p) => p.trim())
        : [];

  if (!blocks.length && !interpretation) return null;

  return (
    <div className="as-narrative-block" data-testid={testId}>
      {blocks.map((para, i) => (
        <p key={i} className="as-section-narrative as-paragraph">
          {para}
        </p>
      ))}
      {interpretation ? (
        <p className="as-section-interpretation" data-testid={testId ? `${testId}-interpretation` : undefined}>
          {interpretation}
        </p>
      ) : null}
    </div>
  );
}

export function ApexScoreScan({ initial }: { initial?: ApexScoreLayer | null }) {
  const data = initial;
  const [open, setOpen] = useState<Record<string, boolean>>({});

  if (!data?.sections?.length) {
    return (
      <section className="sf-stage as-stage" data-testid="apex-score-stage" data-state="loading">
        <p className="sf-empty">Loading APEX composite score…</p>
      </section>
    );
  }

  const composite = data.composite_score;
  const threshold = data.threshold_full_doc ?? 72;
  const tier = scoreTier(composite);
  const clears = data.clears_threshold;

  function toggle(id: string) {
    setOpen((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  return (
    <section className="sf-stage as-stage" data-testid="apex-score-stage" data-tier={tier} data-clears={clears ? "true" : "false"}>
      <header className="sf-head">
        <div>
          <h1 className="sf-title">APEX Composite Score</h1>
          <p className="sf-sub">Full Document §8 · execution threshold ≥ {threshold}</p>
        </div>
      </header>

      <div className="as-hero">
        <div className="sf-gauge as-composite-gauge" data-testid="apex-composite-gauge" aria-label={`Composite score ${composite}`}>
          <svg viewBox="0 0 120 70" className="sf-gauge-svg">
            <path d="M10 60 A50 50 0 0 1 110 60" className="sf-gauge-track" />
            <path
              d="M10 60 A50 50 0 0 1 110 60"
              className={`sf-gauge-fill as-gauge-fill is-${tier}`}
              strokeDasharray="126"
              strokeDashoffset={compositeGaugeOffset(composite)}
            />
          </svg>
          <p className={`as-composite-value is-${tier}`} data-testid="apex-composite-value">
            {fmt(composite, 1)}
          </p>
          <p className="as-composite-label">/ 100</p>
        </div>
        <div className="as-hero-copy">
          <p className={`as-threshold-badge ${clears ? "is-clear" : "is-below"}`} data-testid="apex-threshold-badge">
            {clears ? "Threshold met" : "Below execution threshold"}
          </p>
          <NarrativeBlock
            paragraphs={data.paragraphs}
            narrative={data.narrative}
            interpretation={data.interpretation}
            testId="apex-synthesis"
          />
        </div>
      </div>

      <div className="as-sections" data-testid="apex-score-sections">
        {data.sections.map((section) => {
          const isOpen = open[section.id] ?? section.id === "technicals";
          return (
            <div key={section.id} className="as-section" data-testid={`apex-section-${section.id}`}>
              <button
                type="button"
                className="as-section-head w-full text-left"
                aria-expanded={isOpen}
                onClick={() => toggle(section.id)}
                data-testid={`apex-section-toggle-${section.id}`}
              >
                <span className="as-section-title">{section.title}</span>
                <span className="as-section-score">{fmt(section.score, 0)}</span>
                {section.weight > 0 ? (
                  <span className="as-section-weight">
                    {Math.round(section.weight * 100)}% · +{fmt(section.weighted_contribution, 1)}
                  </span>
                ) : (
                  <span className="as-section-weight">Advisory</span>
                )}
                <span aria-hidden className="text-bronze">{isOpen ? "▾" : "▸"}</span>
              </button>
              {isOpen && (
                <div className="as-section-body">
                  <NarrativeBlock
                    paragraphs={section.paragraphs}
                    narrative={section.narrative}
                    interpretation={section.interpretation}
                    testId={`apex-section-narrative-${section.id}`}
                  />
                  {section.breakdown?.length ? (
                    <dl className="sf-kv as-breakdown">
                      {section.breakdown.map((row) => (
                        <div key={row.label} className="as-breakdown-row">
                          <dt>{row.label}</dt>
                          <dd>
                            <span className="as-breakdown-value">{fmt(row.value)}</span>
                            {row.note ? <span className="as-breakdown-note">{row.note}</span> : null}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
