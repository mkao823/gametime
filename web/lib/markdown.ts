import fs from "fs";
import path from "path";
import matter from "gray-matter";

export interface MarkdownDocument {
  title: string;
  description?: string;
  content: string;
}

const CONTENT_DIR = path.join(process.cwd(), "content");

/** Strip a leading `# Title` line when it duplicates frontmatter title. */
function stripDuplicateH1(body: string, title: string): string {
  const lines = body.split("\n");
  const firstContentIndex = lines.findIndex((line) => line.trim() !== "");
  if (firstContentIndex === -1) {
    return body;
  }

  const firstLine = lines[firstContentIndex].trim();
  const h1Match = firstLine.match(/^#\s+(.+)$/);
  if (h1Match && h1Match[1].trim() === title.trim()) {
    const remaining = [...lines];
    remaining.splice(firstContentIndex, 1);
    if (remaining[firstContentIndex]?.trim() === "") {
      remaining.splice(firstContentIndex, 1);
    }
    return remaining.join("\n").trimStart();
  }

  return body;
}

export function loadMarkdown(filename: string): MarkdownDocument {
  const filePath = path.join(CONTENT_DIR, filename);
  const raw = fs.readFileSync(filePath, "utf-8");
  const { data, content } = matter(raw);

  const title =
    typeof data.title === "string" && data.title.trim()
      ? data.title.trim()
      : filename.replace(/\.md$/, "");

  const description =
    typeof data.description === "string" ? data.description.trim() : undefined;

  return {
    title,
    description,
    content: stripDuplicateH1(content, title),
  };
}
