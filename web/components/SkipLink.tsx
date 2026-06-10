import Link from "next/link";
import styles from "./SkipLink.module.css";

export function SkipLink() {
  return (
    <Link href="#main-content" className={styles.skipLink}>
      Skip to content
    </Link>
  );
}
