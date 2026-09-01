import { useEffect, useRef, useState } from "react";

export type VolCard = {
  id: string;
  title: string;
  bias?: string;
  body: string;
};

export function VolAnalysisCards({ cards }: { cards: VolCard[] }) {
  const [idx, setIdx] = useState(0);
  const swipeX = useRef(0);

  useEffect(() => {
    setIdx((i) => (cards.length ? Math.min(i, cards.length - 1) : 0));
  }, [cards.length]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
      if (e.key === "ArrowRight") {
        e.preventDefault();
        setIdx((i) => Math.min(i + 1, Math.max(cards.length - 1, 0)));
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setIdx((i) => Math.max(i - 1, 0));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cards.length]);

  function go(delta: number) {
    setIdx((i) => Math.min(Math.max(cards.length - 1, 0), Math.max(0, i + delta)));
  }

  const active = cards[idx];

  if (!cards.length) {
    return (
      <p className="text-sm text-faint" data-testid="vol-cards-empty">
        Volatility analysis cards are unavailable for this snapshot.
      </p>
    );
  }

  return (
    <div
      className="vol-carousel"
      data-testid="vol-carousel"
      data-card-count={cards.length}
      onWheel={(e) => {
        if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && Math.abs(e.deltaX) > 24) {
          e.preventDefault();
          go(e.deltaX > 0 ? 1 : -1);
        }
      }}
      onTouchStart={(e) => {
        swipeX.current = e.touches[0].clientX;
      }}
      onTouchEnd={(e) => {
        const dx = e.changedTouches[0].clientX - swipeX.current;
        if (dx < -40) go(1);
        if (dx > 40) go(-1);
      }}
    >
      <button type="button" aria-label="Previous volatility card" data-testid="vol-prev" className="ta-arrow" onClick={() => go(-1)}>
        ‹
      </button>
      <article className="ta-card" data-testid="vol-card" data-bias={active?.bias ?? "neutral"}>
        <p className="ta-card-kicker">
          Volatility · {idx + 1} of {cards.length}
        </p>
        <h2 className="ta-card-title">{active?.title ?? "Analysis"}</h2>
        <p className="ta-card-body">{active?.body ?? ""}</p>
      </article>
      <button type="button" aria-label="Next volatility card" data-testid="vol-next" className="ta-arrow" onClick={() => go(1)}>
        ›
      </button>
    </div>
  );
}
