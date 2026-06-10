import Link from "next/link";
import styles from "./BackLink.module.css";

interface BackLinkProps {
  date: string;
}

export function BackLink({ date }: BackLinkProps) {
  return (
    <Link href={`/?date=${encodeURIComponent(date)}`} className={styles.link}>
      ← Back to slate
    </Link>
  );
}
