import type { ReactNode } from "react";
import styles from "./Callout.module.css";

interface CalloutProps {
  children: ReactNode;
}

export function Callout({ children }: CalloutProps) {
  return <aside className={styles.callout}>{children}</aside>;
}
