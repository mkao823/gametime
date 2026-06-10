import type { GamePrediction } from "@/lib/api-types";
import {
  formatRuns,
  formatScoreline,
  formatWinnerDetail,
} from "@/lib/format";
import styles from "./ScorelineCard.module.css";

interface ScorelineCardProps {
  game: GamePrediction;
}

export function ScorelineCard({ game }: ScorelineCardProps) {
  const scores = formatScoreline(
    game.away,
    game.home,
    game.pred_away_final,
    game.pred_home_final,
    game.winner
  );

  return (
    <div className={styles.card}>
      <p className={styles.sublabel}>Predicted final</p>
      <div className={styles.scoreline} aria-label="Predicted final score">
        <span
          className={
            scores.awayIsWinner ? styles.teamScoreWinner : styles.teamScore
          }
        >
          <span className={styles.teamTri}>{game.away}</span>
          <span className={styles.scoreNum}>{scores.awayScore}</span>
        </span>
        <span className={styles.divider} aria-hidden="true">
          —
        </span>
        <span
          className={
            scores.homeIsWinner ? styles.teamScoreWinner : styles.teamScore
          }
        >
          <span className={styles.teamTri}>{game.home}</span>
          <span className={styles.scoreNum}>{scores.homeScore}</span>
        </span>
      </div>
      <p className={styles.meta}>
        <span className={styles.metaLabel}>Total:</span>{" "}
        {formatRuns(game.pred_total)}
      </p>
      <p className={styles.meta}>
        <span className={styles.metaLabel}>Winner:</span>{" "}
        {formatWinnerDetail(game.home, game.winner, game.win_prob_home)}
      </p>
    </div>
  );
}
