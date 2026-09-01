import { useState } from "react";
import { api } from "../api";
import { formatOrderAccountLabel } from "../lib/orderFormat";
import type { PositionCertificateDetails } from "../components/PositionCertificateModal";
import type { BreakevenValue, PositionRow, StrategyLeg, User } from "../types";

export function usePositionCertificate(options: { isPaper: boolean; accountLabel?: string }) {
  const [selected, setSelected] = useState<PositionCertificateDetails | null>(null);

  function openPosition(position: PositionRow, relatedLegs?: PositionRow[]) {
    const base: PositionCertificateDetails = {
      position,
      relatedLegs,
      strategyName: position.strategy_name ?? undefined,
      entryScore: null,
      accountLabel: options.accountLabel ?? "APEX Account",
      isPaper: options.isPaper,
    };
    setSelected(base);

    void api
      .positionDetail(position.id)
      .then((res) => {
        const cert = res.certificate;
        setSelected((prev) => {
          if (!prev || prev.position.id !== position.id) return prev;
          return {
            ...prev,
            strategyName: cert.strategy_name ?? position.strategy_name ?? prev.strategyName,
            entryScore: cert.entry_composite_score ?? prev.entryScore,
            greeks: cert.greeks ?? prev.greeks,
            strategyLegs: (cert.legs as StrategyLeg[] | undefined)?.length
              ? (cert.legs as StrategyLeg[])
              : prev.strategyLegs,
            breakevens: (cert.breakevens as BreakevenValue[] | undefined)?.length
              ? (cert.breakevens as BreakevenValue[])
              : prev.breakevens,
            breakevenIvAssumption: cert.breakeven_iv_assumption ?? prev.breakevenIvAssumption,
            breakevenAssumptionNote: cert.breakeven_assumption_note ?? prev.breakevenAssumptionNote,
          };
        });
      })
      .catch(() => undefined);
  }

  function dismiss() {
    setSelected(null);
  }

  return { selected, openPosition, dismiss };
}

export function defaultAccountLabel(user: User | null, isPaper: boolean) {
  if (isPaper) return formatOrderAccountLabel(user);
  return "Connected brokerage · read-only";
}
