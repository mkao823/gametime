#!/usr/bin/env python3
"""Apply W6m h2h member wiring on top of W6h (3d66308) sources."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "3d66308"
H2H_BLOB = "0d59fdb1c9c67c055d4240d7caee3f695c4b26aa"


def _git_show(path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{BASE}:{path}"], cwd=ROOT, text=True
    )


def patch_train(t: str) -> str:
    t = t.replace(
        "from gametime.pregame.baseball.models.pitcher import PitcherMember, attach_pitcher",
        "from gametime.pregame.baseball.models.h2h import H2HMember, attach_h2h\n"
        "from gametime.pregame.baseball.models.pitcher import PitcherMember, attach_pitcher",
    )
    t = t.replace(
        "    pitcher_games_path: Path | None = None,\n) -> dict[str, Any]:",
        "    pitcher_games_path: Path | None = None,\n"
        "    league_total_fallback: float = 8.5,\n"
        "    h2h_window: int = 10,\n"
        "    h2h_shrink_k: float = 8.0,\n) -> dict[str, Any]:",
    )
    t = t.replace(
        "    table = attach_elo(table, games, params=elo_params)\n"
        "    train_df, val_df, test_df = split_table_by_season(",
        "    table = attach_elo(table, games, params=elo_params)\n"
        "    table = attach_h2h(table, games, window=h2h_window, shrink_k=h2h_shrink_k)\n"
        "    train_df, val_df, test_df = split_table_by_season(",
    )
    t = t.replace(
        "    elo = EloMember(elo_params)\n    elo.fit(train_df)\n\n    train_games = games[",
        "    elo = EloMember(elo_params)\n    elo.fit(train_df)\n"
        "    h2h = H2HMember(league_total_fallback=league_total_fallback)\n"
        "    h2h.fit(train_df)\n\n    train_games = games[",
    )
    t = t.replace(
        "        | EloMember\n    ] = [\n        lgbm,\n        heuristic,\n"
        "        runs_strength,\n        poisson,\n        pythagorean,\n"
        "        pitcher,\n        elo,\n    ]",
        "        | EloMember\n        | H2HMember\n    ] = [\n        lgbm,\n"
        "        heuristic,\n        runs_strength,\n        poisson,\n"
        "        pythagorean,\n        pitcher,\n        elo,\n        h2h,\n    ]",
    )
    return t


def patch_predict(p: str) -> str:
    p = p.replace(
        "from gametime.pregame.baseball.models.heuristic import HeuristicMember",
        "from gametime.pregame.baseball.models.h2h import H2HMember, attach_h2h, latest_h2h_columns\n"
        "from gametime.pregame.baseball.models.heuristic import HeuristicMember",
    )
    p = p.replace(
        "        pitcher_games_path: str | Path | None = None,\n    ) -> None:",
        "        pitcher_games_path: str | Path | None = None,\n"
        "        league_total_fallback: float = 8.5,\n"
        "        h2h_window: int = 10,\n"
        "        h2h_shrink_k: float = 8.0,\n    ) -> None:",
    )
    p = p.replace(
        "        self.elo = EloMember(self.elo_params)\n        self._pitcher_games = load_pitcher_games(",
        "        self.elo = EloMember(self.elo_params)\n"
        "        self.h2h = H2HMember(league_total_fallback=league_total_fallback)\n"
        "        self._h2h_window = h2h_window\n"
        "        self._h2h_shrink_k = h2h_shrink_k\n"
        "        self._pitcher_games = load_pitcher_games(",
    )
    p = p.replace(
        '        table = attach_elo(table, self.games, params=self.elo_params)\n'
        '        seasontypes = train_seasontypes or ["rg"]',
        '        table = attach_elo(table, self.games, params=self.elo_params)\n'
        "        table = attach_h2h(\n"
        "            table, self.games, window=self._h2h_window, shrink_k=self._h2h_shrink_k\n"
        '        )\n        seasontypes = train_seasontypes or ["rg"]',
    )
    p = p.replace(
        "        self.elo.fit(train_df)\n\n        self._use_stacking = use_stacking",
        "        self.elo.fit(train_df)\n        self.h2h.fit(train_df)\n\n        self._use_stacking = use_stacking",
    )
    p = p.replace(
        "        row_df = row_df.assign(\n            **latest_pitcher_columns(\n"
        "                home=home,\n                away=away,\n"
        "                games=self.games,\n                pitcher_games=self._pitcher_games,\n"
        "            )\n        )\n\n        member_preds: list[MemberPrediction] = [",
        "        row_df = row_df.assign(\n            **latest_pitcher_columns(\n"
        "                home=home,\n                away=away,\n"
        "                games=self.games,\n                pitcher_games=self._pitcher_games,\n"
        "            )\n        )\n        row_df = row_df.assign(\n"
        "            **latest_h2h_columns(\n                self.games,\n"
        "                home=home,\n                away=away,\n"
        "                window=self._h2h_window,\n                shrink_k=self._h2h_shrink_k,\n"
        "            )\n        )\n\n        member_preds: list[MemberPrediction] = [",
    )
    p = p.replace(
        "            self.elo.predict(row_df),\n        ]",
        "            self.elo.predict(row_df),\n            self.h2h.predict(row_df),\n        ]",
    )
    return p


def patch_cli(c: str) -> str:
    c = c.replace(
        "        elo_cfg = pg.get(\"elo\", {})\n        baseball_elo_params = BaseballEloParams(",
        "        elo_cfg = pg.get(\"elo\", {})\n        h2h_cfg = pg.get(\"h2h\", {})\n"
        "        baseball_elo_params = BaseballEloParams(",
        1,
    )
    c = c.replace(
        "            pitcher_games_path=root\n            / data_cfg.get(\n"
        '                "pitcher_games_path", "data/mlb/processed/pitcher_games.parquet"\n'
        "            ),\n        )\n        print(json.dumps(meta, indent=2, default=str))\n"
        "        return\n\n    model_dir = root / pg.get(\"model_dir\", \"models/pregame\")",
        "            pitcher_games_path=root\n            / data_cfg.get(\n"
        '                "pitcher_games_path", "data/mlb/processed/pitcher_games.parquet"\n'
        "            ),\n            league_total_fallback=float(pg.get(\"league_total_fallback\", 8.5)),\n"
        "            h2h_window=int(h2h_cfg.get(\"meeting_window\", 10)),\n"
        "            h2h_shrink_k=float(h2h_cfg.get(\"shrink_k\", 8.0)),\n"
        "        )\n        print(json.dumps(meta, indent=2, default=str))\n"
        "        return\n\n    model_dir = root / pg.get(\"model_dir\", \"models/pregame\")",
        1,
    )
    idx = c.find("if sport.family == \"baseball\":")
    idx2 = c.find("pred = predictor.predict(", idx)
    block = c[idx:idx2]
    if "h2h_cfg" not in block:
        block = block.replace(
            "        elo_cfg = pg.get(\"elo\", {})\n        baseball_elo_params",
            "        elo_cfg = pg.get(\"elo\", {})\n        h2h_cfg = pg.get(\"h2h\", {})\n"
            "        baseball_elo_params",
            1,
        )
    if "h2h_window=int(h2h_cfg" not in block:
        block = block.replace(
            "            pitcher_games_path=pitcher_games_path,\n        )\n",
            "            pitcher_games_path=pitcher_games_path,\n"
            "            league_total_fallback=float(pg.get(\"league_total_fallback\", 8.5)),\n"
            "            h2h_window=int(h2h_cfg.get(\"meeting_window\", 10)),\n"
            "            h2h_shrink_k=float(h2h_cfg.get(\"shrink_k\", 8.0)),\n        )\n",
            1,
        )
    return c[:idx] + block + c[idx2:]


def patch_yaml(y: str) -> str:
    return y.replace(
        "    members: [lgbm, heuristic, runs_strength, poisson, pythagorean, pitcher, elo]\n"
        "    runs_strength_window: 30\n  elo:",
        "    members: [lgbm, heuristic, runs_strength, poisson, pythagorean, pitcher, elo, h2h]\n"
        "    runs_strength_window: 30\n  h2h:\n    meeting_window: 10\n    shrink_k: 8\n  elo:",
    )


H2H_TESTS = '''

def test_attach_h2h_excludes_current_and_future_meetings():
  dates = pd.date_range("2024-04-01", periods=4, freq="D")
  games = pd.DataFrame({"game_id": ["g0","g1","g2","g3"], "game_date": dates, "home_team": ["AAA","BBB","AAA","AAA"], "away_team": ["BBB","AAA","BBB","BBB"], "home_runs": [5,1,999,2], "away_runs": [3,9,0,1], "margin_final": [2,-8,999,1], "season_start_year": [2024]*4, "seasontype": ["rg"]*4})
  enriched = attach_h2h(games[["game_id","season_start_year"]], games, window=10, shrink_k=8.0)
  assert enriched.loc[enriched["game_id"]=="g0","h2h_n_meetings"].iloc[0]==0
  assert enriched.loc[enriched["game_id"]=="g2","h2h_n_meetings"].iloc[0]==2
  assert enriched.loc[enriched["game_id"]=="g2","h2h_raw_margin"].iloc[0]==pytest.approx(-3.0)

def test_grid_search_respects_min_member_weight_eight_members():
  min_w=0.05
  members=[_member(chr(97+i),[9.0]*4,[1.0,-1.0,1.0,-1.0]) for i in range(8)]
  wt,wm=fit_weights(members,np.array([9.0]*4),np.array([1.,-1.,1.,-1.]),step=0.05,min_member_weight=min_w)
  assert all(wt[n]>=min_w-1e-9 for n in wt)
'''


def main() -> None:
    h2h = subprocess.check_output(
        ["git", "show", f"{H2H_BLOB}:src/gametime/pregame/baseball/models/h2h.py"],
        cwd=ROOT,
        text=True,
    )
    (ROOT / "src/gametime/pregame/baseball/models/h2h.py").write_text(h2h)
    (ROOT / "src/gametime/pregame/baseball/train.py").write_text(
        patch_train(_git_show("src/gametime/pregame/baseball/train.py"))
    )
    (ROOT / "src/gametime/pregame/baseball/predict.py").write_text(
        patch_predict(_git_show("src/gametime/pregame/baseball/predict.py"))
    )
    (ROOT / "src/gametime/cli.py").write_text(patch_cli(_git_show("src/gametime/cli.py")))
    (ROOT / "configs/mlb.yaml").write_text(patch_yaml(_git_show("configs/mlb.yaml")))
    tests = _git_show("tests/test_baseball_ensemble.py").replace(
        "from gametime.pregame.baseball.models.elo import attach_elo, fit_baseball_elo",
        "from gametime.pregame.baseball.models.elo import attach_elo, fit_baseball_elo\n"
        "from gametime.pregame.baseball.models.h2h import attach_h2h",
    )
    if "test_attach_h2h" not in tests:
        tests += H2H_TESTS
    (ROOT / "tests/test_baseball_ensemble.py").write_text(tests)
    print("OK")


if __name__ == "__main__":
    main()
