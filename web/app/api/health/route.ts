import { SERVER_API_BASE } from "@/lib/server-api";

export async function GET() {
  try {
    const res = await fetch(`${SERVER_API_BASE}/health`, { cache: "no-store" });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch {
    return Response.json(
      { error: "Failed to reach predictions API" },
      { status: 502 }
    );
  }
}
