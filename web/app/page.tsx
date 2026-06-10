import { Suspense } from "react";
import type { Metadata } from "next";
import { SlateView } from "@/components/SlateView";
import { GameCardSkeleton } from "@/components/GameCardSkeleton";
import styles from "./page.module.css";

export const metadata: Metadata = {
  title: "MLB Slate",
  description: "Daily MLB pregame ensemble predictions.",
};

function SlateFallback() {
  return (
    <div className={styles.page}>
      <h1 className={styles.title}>MLB Slate</h1>
      <div className={styles.fallbackGrid} aria-busy="true" aria-label="Loading">
        {Array.from({ length: 4 }, (_, i) => (
          <GameCardSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}

export default function SlatePage() {
  return (
    <Suspense fallback={<SlateFallback />}>
      <SlateView />
    </Suspense>
  );
}
