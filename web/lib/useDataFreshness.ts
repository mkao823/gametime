import type { HealthResponse } from "./api-types";
import { formatDisplayDate } from "./format";

export interface DataFreshness {
  showBanner: boolean;
  message: string | null;
  healthFailed: boolean;
}

export function useDataFreshness(
  health: HealthResponse | null,
  selectedDate: string,
  healthFailed: boolean
): DataFreshness {
  if (healthFailed) {
    return {
      showBanner: true,
      message: "Could not verify data freshness. Predictions may be outdated.",
      healthFailed: true,
    };
  }

  const gamesMaxDate = health?.games_max_date;
  if (!gamesMaxDate) {
    return { showBanner: false, message: null, healthFailed: false };
  }

  if (gamesMaxDate < selectedDate) {
    return {
      showBanner: true,
      message: `Data last updated ${formatDisplayDate(gamesMaxDate)}. Predictions for ${formatDisplayDate(selectedDate)} may be incomplete until the daily refresh runs.`,
      healthFailed: false,
    };
  }

  return { showBanner: false, message: null, healthFailed: false };
}
