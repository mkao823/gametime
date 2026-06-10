"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./SiteHeader.module.css";

const NAV_ITEMS = [
  { href: "/", label: "Slate", match: (path: string) => path === "/" },
  {
    href: "/methodology",
    label: "Methodology",
    match: (path: string) => path === "/methodology",
  },
  {
    href: "/disclaimer",
    label: "Disclaimer",
    match: (path: string) => path === "/disclaimer",
  },
] as const;

export function SiteHeader() {
  const pathname = usePathname();

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Link href="/" className={styles.wordmark}>
          gametime
        </Link>
        <nav className={styles.nav} aria-label="Main">
          <ul className={styles.navList}>
            {NAV_ITEMS.map((item) => {
              const isActive = item.match(pathname);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className={isActive ? styles.navLinkActive : styles.navLink}
                    aria-current={isActive ? "page" : undefined}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </header>
  );
}
