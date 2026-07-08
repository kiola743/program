"""시장 레짐 필터.

BTC(기준 자산) 종가가 장기 이동평균 위에 있을 때만 "상승 레짐"으로 판단한다.
하락 레짐에서는 신규 매수를 금지해 약세장 진입을 구조적으로 차단한다.
알트코인은 BTC와 동행성이 높아 BTC 레짐 하나로 시장 전체를 필터링한다.
"""

from __future__ import annotations

import pandas as pd


def regime_ok(base_df: pd.DataFrame, ma_period: int = 200) -> pd.Series:
    """기준 자산 캔들에서 시점별 상승 레짐 여부(bool)를 반환한다.

    MA 계산이 불가능한 초기 구간은 True(필터 미적용)로 둔다 —
    데이터 부족을 이유로 백테스트 앞부분 전체를 버리지 않기 위함.
    """
    close = base_df["close"]
    ma = close.rolling(ma_period).mean()
    ok = close > ma
    ok[ma.isna()] = True
    return ok


def latest_regime_ok(base_df: pd.DataFrame, ma_period: int = 200) -> bool:
    """실시간 트레이더용: 가장 최근 시점의 레짐 판정."""
    return bool(regime_ok(base_df, ma_period).iloc[-1])


def align_regime(regime: pd.Series, target_index: pd.Index) -> pd.Series:
    """레짐 시리즈를 다른 마켓의 캔들 인덱스에 맞춘다 (누락 시점은 직전 값 유지)."""
    return regime.reindex(target_index, method="ffill").fillna(True)
