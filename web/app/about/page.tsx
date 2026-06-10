import type { Metadata } from "next";
import { ProseLayout } from "@/components/ProseLayout";
import { loadMarkdown } from "@/lib/markdown";

const doc = loadMarkdown("about.md");

export const metadata: Metadata = {
  title: doc.title,
  description: doc.description,
};

export default function AboutPage() {
  return <ProseLayout title={doc.title} content={doc.content} />;
}
