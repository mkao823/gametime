import type { ReactNode } from "react";
import { SkipLink } from "./SkipLink";
import { SiteHeader } from "./SiteHeader";
import { SiteFooter } from "./SiteFooter";
import styles from "./AppShell.module.css";

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className={styles.shell}>
      <SkipLink />
      <SiteHeader />
      <main id="main-content" className={styles.main}>
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
