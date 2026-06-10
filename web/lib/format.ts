const runsFormatter = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

export function formatRuns(n: number): string {
  return `${runsFormatter.format(n)} runs`;
}

export function formatWinPct(
  home: string,
  winner: string,
  winProbHome: number
): string {
  const pct =
    winner === home
      ? Math.round(winProbHome * 100)
      : 100 - Math.round(winProbHome * 100);
  const side = winner === home ? "home" : "away";
  return `${winner} · ${pct}% ${side} win`;
}

export function formatMargin(
  home: string,
  away: string,
  predMargin: number
): string {
  const favored = predMargin >= 0 ? home : away;
  const absMargin = Math.abs(predMargin);
  return `${favored} \u2212${runsFormatter.format(absMargin)}`;
}

export function formatDisplayDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function localTodayIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
