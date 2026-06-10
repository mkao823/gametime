import type { Metadata } from "next";
import styles from "./page.module.css";

export const metadata: Metadata = {
  title: "MLB Slate",
  description: "Daily MLB pregame ensemble predictions.",
};

export default function SlatePage() {
  return (
    <div className={styles.page}>
      <h1 className={styles.title}>MLB Slate</h1>
      <p className={styles.note}>Predictions load in TASK-24.</p>
    </div>
  );
}
