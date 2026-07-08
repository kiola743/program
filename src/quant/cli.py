"""CLI 진입점: collect / backtest / compare / walkforward / paper / live

사용 예:
    python -m quant.cli collect
    python -m quant.cli compare
    python -m quant.cli walkforward
    python -m quant.cli backtest --strategy volatility_breakout --market KRW-BTC --param k=0.5
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
from quant.backtest.intraday import run_vb_intraday_backtest
from quant.backtest.walkforward import run_walkforward, summarize_folds
from quant.config import env, load_config
from quant.data.collector import fetch_and_cache, load_cached
from quant.exchange.paper import PaperExchange
from quant.exchange.upbit import UpbitExchange
from quant.live.statelog import StateLog
from quant.live.trader import LiveTrader
from quant.notify.discord import DiscordNotifier
from quant.risk.manager import RiskManager
from quant.strategy import STRATEGY_REGISTRY
from quant.strategy.regime import align_regime, regime_ok

def _setup_logging() -> None:
    """콘솔 + 회전 파일(logs/quant.log, 5MB×5개) 동시 로깅."""
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    Path("logs").mkdir(exist_ok=True)
    file_handler = RotatingFileHandler("logs/quant.log", maxBytes=5 * 1024 * 1024,
                                       backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


_setup_logging()
logger = logging.getLogger("quant.cli")


def cmd_collect(args, cfg: dict) -> None:
    data_cfg = cfg["data"]
    jobs = [(cfg["interval"], data_cfg["days"])]
    if getattr(args, "intraday", False):
        jobs.append((data_cfg.get("intraday_interval", "minute15"),
                     data_cfg.get("intraday_days", 180)))

    for market in cfg["markets"]:
        for interval, days in jobs:
            logger.info("수집 시작: %s (%s, %d일)", market, interval, days)
            df = fetch_and_cache(
                market, interval=interval, days=days, db_path=data_cfg["db_path"],
            )
            logger.info("%s(%s) 수집 완료: %d개 캔들 (%s ~ %s)", market, interval, len(df),
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

    if getattr(args, "intraday", False):
        if args.strategy != "volatility_breakout":
            logger.error("--intraday 는 volatility_breakout 전략에서만 지원됩니다 "
                         "(장중 목표가 돌파 체결 재현이 목적)")
            sys.exit(1)
        intraday_interval = cfg["data"].get("intraday_interval", "minute15")
        minute_df = load_cached(args.market, intraday_interval, cfg["data"]["db_path"])
        if minute_df.empty:
            logger.error("분봉 캐시가 없습니다. 먼저 `collect --intraday` 를 실행하세요.")
            sys.exit(1)
        result = run_vb_intraday_backtest(
            df, minute_df, k=float(params.get("k", 0.5)),
            initial_capital=bt["initial_capital"], fee_pct=bt["fee_pct"],
            slippage_pct=bt["slippage_pct"],
        )
        print(f"\n=== {args.market} / volatility_breakout(분봉 정밀) {params} ===")
    else:
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


def _protection_kwargs(cfg: dict) -> dict:
    """라이브와 동일한 보호장치(손절/트레일링)를 백테스트에 적용하기 위한 인자."""
    risk_cfg = cfg.get("risk", {})
    return {
        "stop_loss_pct": risk_cfg.get("stop_loss_pct"),
        "trailing_stop_pct": risk_cfg.get("trailing_stop_pct"),
    }


def _load_regime(cfg: dict) -> "pd.Series | None":
    """config.regime 이 켜져 있으면 기준 자산(BTC) 캐시로 레짐 시리즈를 만든다."""
    regime_cfg = cfg.get("regime", {})
    if not regime_cfg.get("enabled"):
        return None
    base_df = load_cached(regime_cfg.get("market", "KRW-BTC"), cfg["interval"],
                          cfg["data"]["db_path"])
    if base_df.empty:
        logger.warning("레짐 기준 자산 데이터가 없어 레짐 필터를 건너뜁니다")
        return None
    return regime_ok(base_df, int(regime_cfg.get("ma_period", 200)))


def cmd_compare(args, cfg: dict) -> None:
    bt = cfg["backtest"]
    protection = _protection_kwargs(cfg)
    base_regime = _load_regime(cfg)
    if base_regime is not None or any(protection.values()):
        print("(적용 중: 손절/트레일링 스탑"
              + (", BTC 레짐 필터" if base_regime is not None else "") + ")")

    rows = []
    for market in cfg["markets"]:
        df = load_cached(market, cfg["interval"], cfg["data"]["db_path"])
        if df.empty:
            logger.warning("%s 캐시 데이터 없음, 건너뜀 (collect 먼저 실행)", market)
            continue
        market_regime = align_regime(base_regime, df.index) if base_regime is not None else None

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
                                          fee_pct=bt["fee_pct"], slippage_pct=bt["slippage_pct"],
                                          regime=market_regime, **protection)
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


def cmd_walkforward(args, cfg: dict) -> None:
    wf_cfg = cfg.get("walkforward", {"train_days": 365, "test_days": 90})
    bt = cfg["backtest"]
    protection = _protection_kwargs(cfg)
    base_regime = _load_regime(cfg)
    summary_rows = []
    for market in cfg["markets"]:
        df = load_cached(market, cfg["interval"], cfg["data"]["db_path"])
        if df.empty:
            logger.warning("%s 캐시 데이터 없음, 건너뜀 (collect 먼저 실행)", market)
            continue
        market_regime = align_regime(base_regime, df.index) if base_regime is not None else None

        for strat_name, param_spec in cfg["strategies"].items():
            strategy_cls = STRATEGY_REGISTRY[strat_name]
            folds = run_walkforward(
                df, strategy_cls, param_spec,
                train_days=wf_cfg["train_days"], test_days=wf_cfg["test_days"],
                initial_capital=bt["initial_capital"], fee_pct=bt["fee_pct"],
                slippage_pct=bt["slippage_pct"], regime=market_regime, **protection,
            )
            summary = summarize_folds(folds)
            if not summary:
                logger.warning("%s %s 워크포워드 폴드가 없습니다 (데이터가 train+test 길이보다 짧음)",
                              market, strat_name)
                continue

            print(f"\n=== {market} / {strat_name} 워크포워드 ({len(folds)}개 폴드) ===")
            for f in folds:
                print(f"  폴드{f.fold_idx}: train {f.train_start.date()}~{f.train_end.date()} "
                      f"최적파라미터={f.best_params} (train샤프={f.train_sharpe:.2f}) | "
                      f"test {f.test_start.date()}~{f.test_end.date()} "
                      f"OOS수익률={f.test_metrics.total_return_pct:.2f}% "
                      f"OOS샤프={f.test_metrics.sharpe:.2f}")
            print(f"  요약: {summary}")
            summary_rows.append({"마켓": market, "전략": strat_name, **summary})

    if not summary_rows:
        logger.error("워크포워드를 실행할 데이터가 없습니다. 먼저 `collect` 명령을 실행하세요.")
        sys.exit(1)

    print("\n=== 워크포워드 전체 요약 (OOS = Out-Of-Sample, 실제 검증 성과) ===")
    print(pd.DataFrame(summary_rows).to_string(index=False))
    print(
        "\n주의: '수익 폴드 비율'이 낮거나 OOS 평균수익률이 compare 명령의 전체구간 "
        "성과보다 크게 낮다면 해당 파라미터는 과최적화되었을 가능성이 높습니다."
    )


def cmd_paper(args, cfg: dict) -> None:
    live_cfg = cfg["live"]
    exchange = PaperExchange(cfg["paper"]["initial_cash"], db_path=cfg["data"]["db_path"])
    strategy_cls = STRATEGY_REGISTRY[live_cfg["strategy"]]
    strategy = strategy_cls(**live_cfg["params"])
    risk = RiskManager(**cfg["risk"])
    notifier = DiscordNotifier(env("DISCORD_WEBHOOK_URL"))
    state_log = StateLog(cfg["data"]["db_path"])

    trader = LiveTrader(
        exchange=exchange, strategy=strategy, markets=cfg["markets"], risk=risk,
        notifier=notifier, interval=cfg["interval"], lookback=live_cfg["lookback"],
        poll_seconds=live_cfg["poll_seconds"], state_log=state_log,
        regime_cfg=cfg.get("regime"),
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
    state_log = StateLog(cfg["data"]["db_path"])

    trader = LiveTrader(
        exchange=exchange, strategy=strategy, markets=cfg["markets"], risk=risk,
        notifier=notifier, interval=cfg["interval"], lookback=live_cfg["lookback"],
        poll_seconds=live_cfg["poll_seconds"], state_log=state_log,
        regime_cfg=cfg.get("regime"),
    )
    logger.warning("실계좌 자동매매를 시작합니다. 실제 자산이 매매됩니다.")
    trader.run(iterations=args.iterations)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quant")
    parser.add_argument("--config", default=None, help="config.yaml 경로")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="OHLCV 데이터 수집")
    p_collect.add_argument("--intraday", action="store_true",
                           help="분봉도 함께 수집 (정밀 백테스트용)")

    p_bt = sub.add_parser("backtest", help="단일 전략 백테스트")
    p_bt.add_argument("--strategy", required=True, choices=list(STRATEGY_REGISTRY.keys()))
    p_bt.add_argument("--market", required=True)
    p_bt.add_argument("--param", action="append", help="key=value 형태, 여러 개 가능")
    p_bt.add_argument("--intraday", action="store_true",
                      help="분봉 기반 장중 체결 재현 (volatility_breakout 전용)")

    sub.add_parser("compare", help="전략×코인×파라미터 조합 백테스트 비교")

    sub.add_parser("walkforward", help="워크포워드 검증 (과최적화 여부 확인)")

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
        "walkforward": cmd_walkforward, "paper": cmd_paper, "live": cmd_live,
    }
    commands[args.command](args, cfg)


if __name__ == "__main__":
    main()
