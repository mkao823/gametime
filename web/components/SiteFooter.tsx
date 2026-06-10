import Link from "next/link";
import styles from "./SiteFooter.module.css";

export function SiteFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>
        <p className={styles.line}>
          Data: MLB Stats API, pybaseball, Open-Meteo sidecars.
        </p>
        <p className={styles.line}>
          Predictions are not gambling advice. See{" "}
          <Link href="/disclaimer">Disclaimer</Link>.
        </p>
        <p className={styles.copyright}>&copy; gametime</p>
      </div>
    </footer>
  );
}
