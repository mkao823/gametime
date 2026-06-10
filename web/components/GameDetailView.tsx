"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { GamePrediction, HealthResponse } from "@/lib/api-types";
import { formatDisplayDate } from "@/lib/format";
import { BackLink } from "./BackLink";
import { ErrorBanner } from "./ErrorBanner";
import { MemberBreakdown } from "./MemberBreakdown";
import { ScorelineCard } from "./ScorelineCard";
import { ScorelineSkeleton } from "./ScorelineSkeleton";
import styles from "./GameDetailView.module.css";

type LoadState = "loading" | "success" | "not_found" | "error";

function isValidIsoDate(value: string | null): value is string {
  return value !== null && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function orderMembersFromHealth(
  game: GamePrediction,
  ensembleMembers: string[] | undefined
): string[] {
  const keys = new Set([
    ...Object.keys(game.member_totals ?? {}),
    ...Object.keys(game.member_margins ?? {}),
  ]);
  if (!ensembleMembers || ensembleMembers.length === 0) {
    return [...keys].sort();
  }
  const ordered = ensembleMembers.filter((name) => keys.has(name));
  const rest = [...keys].filter((name) => !ordered.includes(name)).sort();
  return [...ordered, ...rest];
}

export function GameDetailView() {
  const searchParams = useSearchParams();
  const home = searchParams.get("home");
  const away = searchParams.get("away");
  const date = searchParams.get("date");

  const [game, setGame] = useState<GamePrediction | null>(null);
  const [memberOrder, setMemberOrder] = useState<string[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [fetchKey, setFetchKey] = useState(0);

  const paramsValid =
    Boolean(home && away) && isValidIsoDate(date);

  const fetchData = useCallback(
    async (signal: AbortSignal) => {
      if (!paramsValid || !home || !away || !date) {
        return;
      }

      setLoadState("loading");

      const gameUrl = `/api/game?home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}&date=${encodeURIComponent(date)}`;

      const [healthResult, gameResult] = await Promise.allSettled([
        fetch("/api/health", { signal }),
        fetch(gameUrl, { signal }),
      ]);

      if (signal.aborted) {
        return;
      }

      let ensembleMembers: string[] | undefined;
      if (healthResult.status === "fulfilled" && healthResult.value.ok) {
        const health = (await healthResult.value.json()) as HealthResponse;
        ensembleMembers = health.ensemble_members;
      }

      if (gameResult.status === "fulfilled") {
        if (gameResult.value.status === 404) {
          setGame(null);
          setMemberOrder([]);
          setLoadState("not_found");
          return;
        }
        if (gameResult.value.ok) {
          const payload = (await gameResult.value.json()) as GamePrediction;
          setGame(payload);
          setMemberOrder(orderMembersFromHealth(payload, ensembleMembers));
          setLoadState("success");
          return;
        }
      }

      setGame(null);
      setMemberOrder([]);
      setLoadState("error");
    },
    [away, date, home, paramsValid]
  );

  useEffect(() => {
    if (!paramsValid) {
      return;
    }
    const controller = new AbortController();
    void fetchData(controller.signal);
    return () => controller.abort();
  }, [fetchData, fetchKey, paramsValid]);

  const handleRetry = () => setFetchKey((k) => k + 1);

  if (!paramsValid) {
    return (
      <div className={styles.page}>
        <p className={styles.message}>
          This page needs a home team, away team, and date. Open a game from the
          slate or pick a date to browse.
        </p>
        <Link href="/" className={styles.inlineLink}>
          Back to slate
        </Link>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <BackLink date={date} />

      <h1 className={styles.title}>
        {away} @ {home}
      </h1>
      <p className={styles.date}>{formatDisplayDate(date)}</p>

      {loadState === "loading" && <ScorelineSkeleton />}

      {loadState === "error" && (
        <ErrorBanner
          message="Couldn't load game prediction. Try again."
          onRetry={handleRetry}
        />
      )}

      {loadState === "not_found" && (
        <div className={styles.notFound}>
          <p className={styles.message}>Game not found on this date.</p>
          <Link
            href={`/?date=${encodeURIComponent(date)}`}
            className={styles.inlineLink}
          >
            Back to slate
          </Link>
        </div>
      )}

      {loadState === "success" && game && (
        <>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Predicted outcome</h2>
            <ScorelineCard game={game} />
          </section>

          <MemberBreakdown game={game} memberOrder={memberOrder} />

          <p className={styles.methodology}>
            <Link href="/methodology" className={styles.inlineLink}>
              How we calculate this
            </Link>
          </p>
        </>
      )}
    </div>
  );
}
