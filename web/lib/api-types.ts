export interface GamePrediction {
  home: string;
  away: string;
  date: string;
  pred_total: number;
  pred_margin: number;
  pred_home_final: number;
  pred_away_final: number;
  winner: string;
  win_prob_home: number;
  is_playoff: boolean;
  home_form_n: number;
  away_form_n: number;
  member_totals?: Record<string, number>;
  member_margins?: Record<string, number>;
}

export interface SlateResponse {
  date: string;
  season_start_year: number;
  games: GamePrediction[];
}

export interface HealthResponse {
  status: string;
  games_max_date: string | null;
  model_dir: string;
  ensemble_members: string[];
}
