import { Suspense } from "react";
import type { Metadata } from "next";
import { GameDetailView } from "@/components/GameDetailView";
import { ScorelineSkeleton } from "@/components/ScorelineSkeleton";
import styles from "./page.module.css";

type PageProps = {
  searchParams: Promise<{
    home?: string;
    away?: string;
    date?: string;
  }>;
};

export async function generateMetadata({
  searchParams,
}: PageProps): Promise<Metadata> {
  const params = await searchParams;
  const { home, away } = params;
  if (home && away) {
    return {
      title: `${away} @ ${home}`,
      description: `MLB pregame ensemble prediction for ${away} at ${home}.`,
    };
  }
  return {
    title: "Game detail",
    description: "MLB game prediction detail.",
  };
}

function GameDetailFallback() {
  return (
    <div className={styles.fallback}>
      <ScorelineSkeleton />
    </div>
  );
}

export default function GameDetailPage() {
  return (
    <Suspense fallback={<GameDetailFallback />}>
      <GameDetailView />
    </Suspense>
  );
}
