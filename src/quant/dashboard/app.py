"""실시간 모니터링 대시보드 (Flask).

live/statelog.py 가 기록한 trade_log/equity_log 테이블과 거래소 어댑터의
현재 잔고/포지션 조회만으로 화면을 그린다. paper 모드는 로컬 SQLite 값을,
live 모드는 실제 업비트 API 잔고를 그대로 보여준다.

실행: python -m quant.dashboard.app --mode paper
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from flask import Flask, render_template_string

from quant.config import env, load_config
from quant.exchange.base import ExchangeAdapter
from quant.exchange.paper import PaperExchange
from quant.exchange.upbit import UpbitExchange
from quant.live.statelog import StateLog

TEMPLATE = """
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>퀀트 트레이더 대시보드</title>
<meta http-equiv="refresh" content="15">
<style>
  :root {
    --surface-1:      #fcfcfb;
    --page:           #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --gridline:       #e1e0d9;
    --border:         rgba(11,11,11,0.10);
    --series-1:       #2a78d6;
    --good:           #0ca30c;
    --critical:       #d03b3b;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --surface-1:      #1a1a19;
      --page:           #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted:     #898781;
      --gridline:       #2c2c2a;
      --border:         rgba(255,255,255,0.10);
      --series-1:       #3987e5;
      --good:           #0ca30c;
      --critical:       #d03b3b;
    }
  }
  * { box-sizing: border-box; }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page); color: var(--text-primary);
    max-width: 960px; margin: 0 auto; padding: 32px 16px 64px;
  }
  h1 { font-size: 1.3rem; font-weight: 600; margin-bottom: 4px; }
  .subtitle { color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 24px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 28px; }
  .tile {
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px 18px;
  }
  .tile .label { color: var(--text-secondary); font-size: 0.82rem; margin-bottom: 6px; }
  .tile .value { font-size: 1.5rem; font-weight: 600; }
  .tile .value.good { color: var(--good); }
  .tile .value.critical { color: var(--critical); }
  h2 { font-size: 1rem; font-weight: 600; margin: 28px 0 10px; color: var(--text-secondary); }
  table { border-collapse: collapse; width: 100%; background: var(--surface-1); border-radius: 10px; overflow: hidden; }
  th, td {
    border-bottom: 1px solid var(--gridline); padding: 10px 14px; text-align: right;
    font-variant-numeric: tabular-nums; font-size: 0.9rem;
  }
  th:first-child, td:first-child { text-align: left; }
  th { color: var(--text-muted); font-weight: 500; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.02em; }
  td.good { color: var(--good); } td.critical { color: var(--critical); }
  .empty-row td { color: var(--text-muted); text-align: center; padding: 20px; }
  .chart-card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px 8px; }
  .chart-card svg { width: 100%; height: auto; display: block; }
  .footer-note { color: var(--text-muted); font-size: 0.8rem; margin-top: 24px; }
  .error { color: var(--critical); background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
</style>
</head>
<body>
  <h1>퀀트 트레이더 대시보드</h1>
  <div class="subtitle">모드: {{ mode }} · 마켓: {{ markets|join(', ') }} · 15초마다 자동 새로고침</div>

  {% if error %}
  <div class="error">{{ error }}</div>
  {% else %}

  <div class="tiles">
    <div class="tile">
      <div class="label">현금</div>
      <div class="value">{{ "{:,.0f}".format(cash) }}원</div>
    </div>
    <div class="tile">
      <div class="label">총자산</div>
      <div class="value">{{ "{:,.0f}".format(equity) }}원</div>
    </div>
    <div class="tile">
      <div class="label">평가손익</div>
      <div class="value {{ 'good' if unrealized >= 0 else 'critical' }}">
        {{ "{:+,.0f}".format(unrealized) }}원
      </div>
    </div>
  </div>

  {% if equity_points %}
  <h2>자산 추이 (최근 {{ equity_points|length }}개 스냅샷)</h2>
  <div class="chart-card">{{ equity_svg|safe }}</div>
  {% endif %}

  <h2>보유 포지션</h2>
  <table>
    <tr><th>마켓</th><th>수량</th><th>평단가</th><th>현재가</th><th>평가손익(%)</th></tr>
    {% for p in positions %}
    <tr>
      <td>{{ p.market }}</td>
      <td>{{ "%.8f"|format(p.qty) }}</td>
      <td>{{ "{:,.0f}".format(p.avg_price) }}</td>
      <td>{{ "{:,.0f}".format(p.price) }}</td>
      <td class="{{ 'good' if p.pnl_pct >= 0 else 'critical' }}">{{ "{:+.2f}".format(p.pnl_pct) }}%</td>
    </tr>
    {% else %}
    <tr class="empty-row"><td colspan="5">보유 중인 포지션 없음</td></tr>
    {% endfor %}
  </table>

  <h2>최근 체결 (최대 20건)</h2>
  <table>
    <tr><th>시각</th><th>마켓</th><th>구분</th><th>가격</th><th>수량</th><th>금액</th></tr>
    {% for t in trades %}
    <tr>
      <td>{{ t.ts[:19] }}</td>
      <td>{{ t.market }}</td>
      <td>{{ "매수" if t.side == "buy" else "매도" }}</td>
      <td>{{ "{:,.0f}".format(t.price) }}</td>
      <td>{{ "%.8f"|format(t.qty) }}</td>
      <td>{{ "{:,.0f}".format(t.krw_amount) }}</td>
    </tr>
    {% else %}
    <tr class="empty-row"><td colspan="6">체결 내역 없음 (트레이더가 아직 매매하지 않았습니다)</td></tr>
    {% endfor %}
  </table>

  <p class="footer-note">
    이 화면은 참고용 모니터링 도구이며 매매 판단은 트레이더 프로세스(paper/live)가 별도로 수행합니다.
  </p>
  {% endif %}
</body>
</html>
"""


def _render_equity_sparkline(points: list[float], width: int = 900, height: int = 160) -> str:
    """자산 스냅샷을 2px 라인 SVG로 그린다 (series-1 hue, 단일 시리즈라 범례 생략)."""
    if len(points) < 2:
        return ""
    pad = 12
    lo, hi = min(points), max(points)
    span = (hi - lo) or 1.0
    n = len(points)
    step = (width - 2 * pad) / (n - 1)

    def xy(i: int, v: float) -> tuple[float, float]:
        x = pad + i * step
        y = height - pad - (v - lo) / span * (height - 2 * pad)
        return x, y

    coords = [xy(i, v) for i, v in enumerate(points)]
    path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    last_x, last_y = coords[-1]

    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="{path}" fill="none" stroke="var(--series-1)" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round" />'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="4.5" fill="var(--series-1)" '
        f'stroke="var(--surface-1)" stroke-width="2" />'
        f"</svg>"
    )


def _build_exchange(cfg: dict, mode: str) -> ExchangeAdapter:
    if mode == "paper":
        return PaperExchange(cfg["paper"]["initial_cash"], db_path=cfg["data"]["db_path"])
    return UpbitExchange(env("UPBIT_ACCESS_KEY"), env("UPBIT_SECRET_KEY"))


def create_app(cfg: dict, mode: str) -> Flask:
    app = Flask(__name__)
    db_path = Path(cfg["data"]["db_path"])
    markets = cfg["markets"]
    StateLog(db_path)  # trade_log/equity_log 테이블이 없으면 생성 (트레이더 미실행 상태 대비)

    @app.route("/")
    def index():
        error = None
        cash = equity = unrealized = 0.0
        positions: list[dict] = []
        trades: list[dict] = []
        equity_points: list[float] = []
        equity_svg = ""

        try:
            exchange = _build_exchange(cfg, mode)
            cash = exchange.get_cash()
            equity = cash
            for market in markets:
                pos = exchange.get_position(market)
                if pos is None:
                    continue
                try:
                    price = exchange.get_current_price(market)
                except Exception:
                    price = pos.avg_price
                pnl_pct = (price / pos.avg_price - 1) * 100 if pos.avg_price else 0.0
                positions.append({
                    "market": market, "qty": pos.qty, "avg_price": pos.avg_price,
                    "price": price, "pnl_pct": pnl_pct,
                })
                equity += pos.qty * price
            unrealized = sum(p["qty"] * (p["price"] - p["avg_price"]) for p in positions)
        except Exception as e:
            error = f"거래소 조회 실패: {e} (live 모드는 .env 의 UPBIT_ACCESS_KEY/SECRET_KEY 확인)"

        if db_path.exists():
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            trades = [dict(r) for r in conn.execute(
                "SELECT ts, market, side, price, qty, krw_amount FROM trade_log "
                "WHERE exchange=? ORDER BY ts DESC LIMIT 20", (mode,),
            ).fetchall()]
            equity_points = [r[0] for r in conn.execute(
                "SELECT equity FROM equity_log WHERE exchange=? ORDER BY ts ASC "
                "LIMIT 200", (mode,),
            ).fetchall()]
            conn.close()
            if equity_points:
                equity_svg = _render_equity_sparkline(equity_points)

        return render_template_string(
            TEMPLATE, mode=mode, markets=markets, error=error,
            cash=cash, equity=equity, unrealized=unrealized,
            positions=positions, trades=trades,
            equity_points=equity_points, equity_svg=equity_svg,
        )

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None, help="config.yaml 경로")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--host", default="127.0.0.1",
                        help="바인딩 주소 (Docker 등 컨테이너에서는 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    cfg = load_config(args.config)
    app = create_app(cfg, args.mode)
    print(f"대시보드 실행: http://{args.host}:{args.port} (모드={args.mode})")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
