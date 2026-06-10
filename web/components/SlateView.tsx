"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { HealthResponse, SlateResponse } from "@/lib/api-types";
import { localTodayIso } from "@/lib/format";
import { useDataFreshness } from "@/lib/useDataFreshness";
import { DatePicker } from "./DatePicker";
import { EmptySlate } from "./EmptySlate";
import { ErrorBanner } from "./ErrorBanner";
import { FreshnessBanner } from "./FreshnessBanner";
import { GameCard } from "./GameCard";
import { GameCardSkeleton } from "./GameCardSkeleton";
import styles from "./SlateView.module.css";

const SKELETON_COUNT = 4;

type LoadState = "loading" | "success" | "error";

function parseDateParam(param: string | null): string {
  if (param && /^\d{4}-\d{2}-\d{2}$/.test(param)) {
    return param;
  }
  return localTodayIso();
}

export function SlateView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const selectedDate = parseDateParam(searchParams.get("date"));

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthFailed, setHealthFailed] = useState(false);
  const [slate, setSlate] = useState<SlateResponse | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [fetchKey, setFetchKey] = useState(0);

  const freshness = useDataFreshness(health, selectedDate, healthFailed);

  const setDate = useCallback(
    (date: string) => {
      router.replace(`/?date=${date}`);
    },
    [router]
  );

  const fetchData = useCallback(async (date: string, signal: AbortSignal) => {
    setLoadState("loading");

    const [healthResult, slateResult] = await Promise.allSettled([
      fetch("/api/health", { signal }),
      fetch(`/api/slate?date=${encodeURIComponent(date)}`, { signal }),
    ]);

    if (signal.aborted) {
      return;
    }

    if (healthResult.status === "fulfilled" && healthResult.value.ok) {
      setHealth((await healthResult.value.json()) as HealthResponse);
      setHealthFailed(false);
    } else {
      setHealth(null);
      setHealthFailed(true);
    }

    if (slateResult.status === "fulfilled" && slateResult.value.ok) {
      setSlate((await slateResult.value.json()) as SlateResponse);
      setLoadState("success");
    } else {
      setSlate(null);
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchData(selectedDate, controller.signal);
    return () => controller.abort();
  }, [selectedDate, fetchKey, fetchData]);

  const handleRetry = () => setFetchKey((k) => k + 1);

  const games = slate?.games ?? [];
  const isLoading = loadState === "loading";
  const hasError = loadState === "error";

  const metaLine = isLoading
    ? "Loading…"
    : games.length === 0
      ? "No games scheduled"
      : `${games.length} game${games.length === 1 ? "" : "s"} · Regular season`;

  return (
    <div className={styles.page}>
      {freshness.showBanner && freshness.message && (
        <FreshnessBanner
          message={freshness.message}
          healthFailed={freshness.healthFailed}
        />
      )}

      <h1 className={styles.title}>MLB Slate</h1>

      <DatePicker
        value={selectedDate}
        onChange={setDate}
        disabled={isLoading}
      />

      <p className={styles.meta}>{metaLine}</p>

      {hasError && <ErrorBanner onRetry={handleRetry} />}

      {isLoading && (
        <div className={styles.grid} aria-busy="true" aria-label="Loading games">
          {Array.from({ length: SKELETON_COUNT }, (_, i) => (
            <GameCardSkeleton key={i} />
          ))}
        </div>
      )}

      {!isLoading && !hasError && games.length === 0 && <EmptySlate />}

      {!isLoading && !hasError && games.length > 0 && (
        <div className={styles.grid}>
          {games.map((game) => (
            <GameCard key={`${game.away}-${game.home}-${game.date}`} game={game} />
          ))}
        </div>
      )}
    </div>
  );
}
