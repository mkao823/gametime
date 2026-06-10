"use client";

import { useId, useState } from "react";
import type { GamePrediction } from "@/lib/api-types";
import { formatMemberMargin, formatScoreValue } from "@/lib/format";
import styles from "./MemberBreakdown.module.css";

interface MemberBreakdownProps {
  game: GamePrediction;
  memberOrder: string[];
}

function hasMemberData(game: GamePrediction): boolean {
  const totals = game.member_totals ?? {};
  const margins = game.member_margins ?? {};
  return Object.keys(totals).length > 0 || Object.keys(margins).length > 0;
}

export function MemberBreakdown({ game, memberOrder }: MemberBreakdownProps) {
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();
  const toggleId = useId();

  if (!hasMemberData(game)) {
    return null;
  }

  const totals = game.member_totals ?? {};
  const margins = game.member_margins ?? {};
  const members =
    memberOrder.length > 0
      ? memberOrder.filter((name) => name in totals || name in margins)
      : [
          ...new Set([
            ...Object.keys(totals),
            ...Object.keys(margins),
          ]),
        ].sort();

  return (
    <section className={styles.section}>
      <h2 className={styles.heading}>
        <button
          type="button"
          id={toggleId}
          className={styles.toggle}
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={() => setExpanded((open) => !open)}
        >
          Member breakdown
          <span className={styles.chevron} aria-hidden="true">
            {expanded ? "▲" : "▼"}
          </span>
        </button>
      </h2>
      <div
        id={panelId}
        className={styles.panel}
        role="region"
        aria-labelledby={toggleId}
        hidden={!expanded}
      >
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Member</th>
                <th scope="col">Total</th>
                <th scope="col">Margin</th>
              </tr>
            </thead>
            <tbody>
              {members.map((name) => (
                <tr key={name}>
                  <td className={styles.memberName}>{name}</td>
                  <td className={styles.num}>
                    {name in totals ? formatScoreValue(totals[name]) : "—"}
                  </td>
                  <td className={styles.num}>
                    {name in margins
                      ? formatMemberMargin(margins[name])
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
