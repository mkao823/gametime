import styles from "./FreshnessBanner.module.css";

interface FreshnessBannerProps {
  message: string;
  healthFailed?: boolean;
}

export function FreshnessBanner({ message, healthFailed }: FreshnessBannerProps) {
  return (
    <div
      className={healthFailed ? styles.bannerMuted : styles.banner}
      role="status"
    >
      {!healthFailed && <span className={styles.icon} aria-hidden="true">⚠</span>}
      <p className={styles.text}>{message}</p>
    </div>
  );
}
