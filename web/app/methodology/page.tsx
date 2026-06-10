import type { Metadata } from "next";
import Link from "next/link";
import { ProseLayout } from "@/components/ProseLayout";
import { loadMarkdown } from "@/lib/markdown";

const doc = loadMarkdown("methodology.md");

export const metadata: Metadata = {
  title: doc.title,
  description: doc.description,
};

export default function MethodologyPage() {
  return (
    <ProseLayout
      title={doc.title}
      content={doc.content}
      footer={
        <p>
          See also: <Link href="/disclaimer">Disclaimer</Link>
        </p>
      }
    />
  );
}
