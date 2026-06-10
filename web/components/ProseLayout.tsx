import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import styles from "./ProseLayout.module.css";

interface ProseLayoutProps {
  title: string;
  content: string;
  callout?: ReactNode;
  footer?: ReactNode;
}

export function ProseLayout({ title, content, callout, footer }: ProseLayoutProps) {
  return (
    <article className={styles.article}>
      <h1 className={styles.title}>{title}</h1>
      {callout}
      <div className={styles.prose}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
      {footer ? <footer className={styles.footer}>{footer}</footer> : null}
    </article>
  );
}
