import Link from "next/link";
import type { GamePrediction } from "@/lib/api-types";
import {
  formatMargin,
  formatRuns,
  formatWinPct,
} from "@/lib/format";
import styles from "./GameCard.module.css";

interface GameCardProps {
  game: GamePrediction;
}

function gameCardLabel(game: GamePrediction): string {
  const total = formatRuns(game.pred_total);
  const pick = formatWinPct(game.home, game.winner, game.win_prob_home);
  return `${game.away} at ${game.home}, predicted total ${total}, pick ${pick}`;
}

export function GameCard({ game }: GameCardProps) {
  const href = `/mlb/game?home=${encodeURIComponent(game.home)}&away=${encodeURIComponent(game.away)}&date=${encodeURIComponent(game.date)}`;
  const homeWins = game.winner === game.home;
  const awayWins = game.winner === game.away;

  return (
    <article className={styles.card}>
      <Link
        href={href}
        className={styles.link}
        aria-label={gameCardLabel(game)}
      >
        <div className={styles.matchup}>
          <span
            className={awayWins ? styles.teamWinner : styles.team}
          >
            {game.away}
          </span>
          <span className={styles.at}>@</span>
          <span
            className={homeWins ? styles.teamWinner : styles.team}
          >
            {game.home}
          </span>
          {game.is_playoff && (
            <span className={styles.badge}>Postseason</span>
          )}
        </div>

        <div className={styles.stat}>
          <span className={styles.statLabel}>Predicted total</span>
          <span className={styles.statValue}>{formatRuns(game.pred_total)}</span>
        </div>

        <div className={homeWins ? styles.pickWinner : styles.pick}>
          <span className={styles.statLabel}>Pick</span>
          <span className={styles.statValue}>
            {formatWinPct(game.home, game.winner, game.win_prob_home)}
          </span>
        </div>

        <div className={styles.stat}>
          <span className={styles.statLabel}>Margin</span>
          <span className={styles.statValue}>
            {formatMargin(game.home, game.away, game.pred_margin)}
          </span>
        </div>
      </Link>
    </article>
  );
}
