import { type NextRequest } from "next/server";
import { SERVER_API_BASE } from "@/lib/server-api";

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const home = searchParams.get("home");
  const away = searchParams.get("away");
  const date = searchParams.get("date");
  const regularSeason = searchParams.get("regular_season") ?? "true";

  const url = new URL(`${SERVER_API_BASE}/v1/game`);
  if (home) {
    url.searchParams.set("home", home);
  }
  if (away) {
    url.searchParams.set("away", away);
  }
  if (date) {
    url.searchParams.set("date", date);
  }
  url.searchParams.set("regular_season", regularSeason);
  url.searchParams.set("include_members", "true");

  try {
    const res = await fetch(url, { cache: "no-store" });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch {
    return Response.json(
      { error: "Failed to reach predictions API" },
      { status: 502 }
    );
  }
}
