from gametime.config import apply_sport_defaults, load_config, project_root


def test_wnba_minimal_config_gets_sport_scoped_paths():
    cfg = apply_sport_defaults({"sport": "wnba"})
    assert cfg["evaluate"]["report_dir"] == "reports/wnba/eval"
    assert cfg["live"]["log_dir"] == "data/wnba/live_predictions"
    assert cfg["pregame"]["report_path"] == "reports/wnba/eval/pregame_summary.json"
    assert cfg["train"]["model_dir"] == "models/wnba"


def test_nba_minimal_config_keeps_legacy_paths():
    cfg = apply_sport_defaults({"sport": "nba"})
    assert cfg["evaluate"]["report_dir"] == "reports/eval"
    assert cfg["live"]["log_dir"] == "data/live_predictions"


def test_wnba_yaml_loads_sport_scoped_paths():
    cfg = load_config(project_root() / "configs/wnba.yaml")
    assert cfg["sport"] == "wnba"
    assert cfg["evaluate"]["report_dir"] == "reports/wnba/eval"
    assert cfg["data"]["processed_dir"] == "data/wnba/processed"
