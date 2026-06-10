import type { Metadata } from "next";
import { Callout } from "@/components/Callout";
import { ProseLayout } from "@/components/ProseLayout";
import { loadMarkdown } from "@/lib/markdown";

const doc = loadMarkdown("disclaimer.md");

export const metadata: Metadata = {
  title: doc.title,
  description: doc.description,
};

export default function DisclaimerPage() {
  return (
    <ProseLayout
      title={doc.title}
      content={doc.content}
      callout={
        <Callout>Not gambling advice. Read carefully.</Callout>
      }
    />
  );
}
