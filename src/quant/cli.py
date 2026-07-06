"""CLI 진입점: collect / backtest / compare / paper / live

사용 예:
    python -m quant.cli collect
    python -m quant.cli compare
    python -m quant.cli backtest --strategy volatility_breakout --market KRW-BTC --k 0.5
    python -m quant.cli paper
    python -m quant.cli live --live   (config.live.live_enabled: true 도 필요)
"""

from __future__ import annotations

import argparse
import itertools
import logging
import sys

import pandas as pd

from quant.backtest.engine import buy_and_hold, run_backtest
from quant.config import env, load_config
from quant.data.collector import fetch_and_cache, load_cached
from quant.exchange.paper import PaperExchange
from quant.exchange.upbit import UpbitExchange
from quant.live.trader import LiveTrader
from quant.notify.discord import DiscordNotifier
from quant.risk.manager import RiskManager
from quant.strategy import STRATEGY_REGISTRY

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("quant.cli")


def cmd_collect(args, cfg: dict) -> None:
    for market in cfg["markets"]:
        logger.info("수집 시작: %s (%s, %d일)", market, cfg["interval"], cfg["data"]["days"])
        df = fetch_and_cache(
            market, interval=cfg["interval"], days=cfg["data"]["days"],
            db_path=cfg["data"]["db_path"],
        )
        logger.info("%s 수집 완료: %d개 캔들 (%s ~ %s)", market, len(df),
                    df.index.min() if len(df) else "-", df.index.max() if len(df) else "-")


def _param_grid(param_spec: dict) -> list[dict]:
    keys = list(param_spec.keys())
    combos = itertools.product(*param_spec.values())
    return [dict(zip(keys, values)) for values in combos]


def cmd_backtest(args, cfg: dict) -> None:
    df = load_cached(args.market, cfg["interval"], cfg["data"]["db_path"])
    if df.empty:
        logger.error("캐시된 데이터가 없습니다. 먼저 `collect` 명령을 실행하세요.")
        sys.exit(1)

    strategy_cls = STRATEGY_REGISTRY[args.strategy]
    params = _parse_extra_params(args.param)
    strategy = strategy_cls(**params)

    bt = cfg["backtest"]
    result = run_backtest(df, strategy, initial_capital=bt["initial_capital"],
                          fee_pct=bt["fee_pct"], slippage_pct=bt["slippage_pct"])
    print(f"\n=== {args.market} / {strategy.name} {params} ===")
    for k, v in result.metrics.as_dict().items():
        print(f"  {k}: {v}")


def _parse_extra_params(param_list: list[str] | None) -> dict:
    params = {}
    for item in param_list or []:
        key, _, value = item.partition("=")
        try:
            params[key] = float(value) if "." in value else int(value)
        except ValueError:
            params[key] = value
    return params


def cmd_compare(args, cfg: dict) -> None:
    bt = cfg["backtest"]
    rows = []
    for market in cfg["markets"]:
        df = load_cached(market, cfg["interval"], cfg["data"]["db_path"])
        if df.empty:
            logger.warning("%s 캐시 데이터 없음, 건너뜀 (collect 먼저 실행)", market)
            continue

        bh_equity = buy_and_hold(df, bt["initial_capital"], bt["fee_pct"])
        bh_return = (bh_equity.iloc[-1] / bh_equity.iloc[0] - 1) * 100
        rows.append({
            "마켓": market, "전략": "buy_and_hold", "파라미터": "-",
            "총수익률(%)": round(bh_return, 2), "CAGR(%)": "-", "MDD(%)": "-",
            "샤프비율": "-", "승률(%)": "-", "거래횟수": "-",
        })

        for strat_name, param_spec in cfg["strategies"].items():
            strategy_cls = STRATEGY_REGISTRY[strat_name]
            for params in _param_grid(param_spec):
                strategy = strategy_cls(**params)
                try:
                    result = run_backtest(df, strategy, initial_capital=bt["initial_capital"],
                                          fee_pct=bt["fee_pct"], slippage_pct=bt["slippage_pct"])
                except ValueError as e:
                    logger.warning("%s %s %s 백테스트 실패: %s", market, strat_name, params, e)
                    continue
                m = result.metrics.as_dict()
                rows.append({"마켓": market, "전략": strat_name, "파라미터": str(params), **m})

    if not rows:
        logger.error("비교할 데이터가 없습니다. 먼저 `collect` 명령을 실행하세요.")
        sys.exit(1)

    table = pd.DataFrame(rows)
    print(table.to_string(index=False))

    ranked = table[table["전략"] != "buy_and_hold"].copy()
    if not ranked.empty:
        ranked = ranked.sort_values("샤프비율", ascending=False)
        print("\n=== 샤프비율 상위 5개 (buy&hold 제외) ===")
        print(ranked.head(5).to_string(index=False))


def cmd_paper(args, cfg: dict) -> None:
    live_cfg = cfg["live"]
    exchange = PaperExchange(cfg["paper"]["initial_cash"], db_path=cfg["data"]["db_path"])
    strategy_cls = STRATEGY_REGISTRY[live_cfg["strategy"]]
    strategy = strategy_cls(**live_cfg["params"])
    risk = RiskManager(**cfg["risk"])
    notifier = DiscordNotifier(env("DISCORD_WEBHOOK_URL"))

    trader = LiveTrader(
        exchange=exchange, strategy=strategy, markets=cfg["markets"], risk=risk,
        notifier=notifier, interval=cfg["interval"], lookback=live_cfg["lookback"],
        poll_seconds=live_cfg["poll_seconds"],
    )
    trader.run(iterations=args.iterations)


def cmd_live(args, cfg: dict) -> None:
    live_cfg = cfg["live"]
    if not (args.live and live_cfg.get("live_enabled")):
        logger.error(
            "실주문이 비활성화되어 있습니다. config.yaml 의 live.live_enabled: true "
            "와 CLI --live 플래그가 모두 필요합니다. (안전장치)"
        )
        sys.exit(1)

    access_key = env("UPBIT_ACCESS_KEY")
    secret_key = env("UPBIT_SECRET_KEY")
    if not access_key or not secret_key:
        logger.error(".env 에 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 를 설정하세요.")
        sys.exit(1)

    exchange = UpbitExchange(access_key, secret_key)
    strategy_cls = STRATEGY_REGISTRY[live_cfg["strategy"]]
    strategy = strategy_cls(**live_cfg["params"])
    risk = RiskManager(**cfg["risk"])
    notifier = DiscordNotifier(env("DISCORD_WEBHOOK_URL"))

    trader = LiveTrader(
        exchange=exchange, strategy=strategy, markets=cfg["markets"], risk=risk,
        notifier=notifier, interval=cfg["interval"], lookback=live_cfg["lookback"],
        poll_seconds=live_cfg["poll_seconds"],
    )
    logger.warning("실계좌 자동매매를 시작합니다. 실제 자산이 매매됩니다.")
    trader.run(iterations=args.iterations)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quant")
    parser.add_argument("--config", default=None, help="config.yaml 경로")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("collect", help="OHLCV 데이터 수집")

    p_bt = sub.add_parser("backtest", help="단일 전략 백테스트")
    p_bt.add_argument("--strategy", required=True, choices=list(STRATEGY_REGISTRY.keys()))
    p_bt.add_argument("--market", required=True)
    p_bt.add_argument("--param", action="append", help="key=value 형태, 여러 개 가능")

    sub.add_parser("compare", help="전략×코인×파라미터 조합 백테스트 비교")

    p_paper = sub.add_parser("paper", help="페이퍼 트레이딩 (가상 자금)")
    p_paper.add_argument("--iterations", type=int, default=None,
                        help="반복 횟수 제한 (테스트용, 기본은 무한루프)")

    p_live = sub.add_parser("live", help="실계좌 자동매매 (주의: 실제 자금 사용)")
    p_live.add_argument("--live", action="store_true", help="실주문 활성화 확인 플래그")
    p_live.add_argument("--iterations", type=int, default=None)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load_config(args.config)

    commands = {
        "collect": cmd_collect, "backtest": cmd_backtest, "compare": cmd_compare,
        "paper": cmd_paper, "live": cmd_live,
    }
    commands[args.command](args, cfg)


if __name__ == "__main__":
    main()
