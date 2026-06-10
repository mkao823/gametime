import type { Metadata } from "next";
import styles from "./page.module.css";

export const metadata: Metadata = {
  title: "Game detail",
  description: "MLB game prediction detail.",
};

export default function GameDetailStubPage() {
  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Game detail</h1>
      <p className={styles.note}>Game detail — TASK-25</p>
    </div>
  );
}
