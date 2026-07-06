from quant.dashboard.app import _render_equity_sparkline, create_app


def test_render_equity_sparkline_needs_two_points():
    assert _render_equity_sparkline([]) == ""
    assert _render_equity_sparkline([100.0]) == ""


def test_render_equity_sparkline_produces_svg():
    svg = _render_equity_sparkline([100.0, 110.0, 90.0, 120.0])
    assert svg.startswith("<svg")
    assert "path" in svg


def test_dashboard_index_renders_without_positions(tmp_path):
    cfg = {
        "markets": ["KRW-BTC"],
        "data": {"db_path": str(tmp_path / "quant.db")},
        "paper": {"initial_cash": 1_000_000},
    }
    app = create_app(cfg, mode="paper")
    client = app.test_client()
    resp = client.get("/")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "1,000,000" in body
    assert "보유 중인 포지션 없음" in body
