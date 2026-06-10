import styles from "./ScorelineSkeleton.module.css";

export function ScorelineSkeleton() {
  return (
    <div className={styles.wrapper} aria-busy="true" aria-label="Loading prediction">
      <div className={styles.card}>
        <div className={`${styles.line} ${styles.lineShort}`} />
        <div className={`${styles.line} ${styles.lineScore}`} />
        <div className={styles.line} />
        <div className={`${styles.line} ${styles.lineMedium}`} />
      </div>
      <div className={styles.tableCard}>
        <div className={`${styles.line} ${styles.lineShort}`} />
        <div className={styles.tableRow} />
      </div>
    </div>
  );
}
