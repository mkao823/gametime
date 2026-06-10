import styles from "./ErrorBanner.module.css";

interface ErrorBannerProps {
  message?: string;
  onRetry: () => void;
}

export function ErrorBanner({
  message = "Couldn't load slate. Try again.",
  onRetry,
}: ErrorBannerProps) {
  return (
    <div className={styles.banner} role="alert">
      <p className={styles.text}>{message}</p>
      <button type="button" className={styles.retryButton} onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
