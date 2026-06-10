import styles from "./EmptySlate.module.css";

export function EmptySlate() {
  return (
    <div className={styles.empty}>
      <span className={styles.icon} aria-hidden="true">
        📅
      </span>
      <h2 className={styles.title}>No games on this date</h2>
      <p className={styles.text}>
        Try another date or check back during the regular season.
      </p>
    </div>
  );
}
