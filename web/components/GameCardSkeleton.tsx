import styles from "./GameCardSkeleton.module.css";

export function GameCardSkeleton() {
  return (
    <div className={styles.card} aria-hidden="true">
      <div className={`${styles.line} ${styles.lineShort}`} />
      <div className={styles.line} />
      <div className={styles.line} />
      <div className={`${styles.line} ${styles.lineMedium}`} />
    </div>
  );
}
