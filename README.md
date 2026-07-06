# 한국 코인/주식 퀀트 자동매매 시스템

업비트(코인) 시세로 전략을 백테스트하고, 페이퍼 트레이딩으로 검증한 뒤, 실계좌 자동매매까지
이어지는 파이프라인입니다. 한국주식(한국투자증권 KIS) 확장을 염두에 두고 거래소/전략이
분리되어 있습니다.

**주의: 어떤 전략도 수익을 보장하지 않습니다.** 반드시 백테스트 → 페이퍼 트레이딩(최소 2~4주)
→ 소액 실전 순서로 검증한 뒤 자금을 투입하세요.

## 구조

```
config/config.yaml        전략 파라미터, 대상 코인, 리스크 한도
config/.env.example        API 키/웹훅 템플릿 (복사해서 .env 로 사용)
src/quant/
  exchange/                거래소 어댑터 (upbit, paper, kis_stub) — 공통 인터페이스
  data/collector.py        OHLCV 수집 + SQLite 캐시
  strategy/                변동성 돌파, MA 모멘텀, 평균회귀(RSI+볼린저)
  backtest/                벡터화 백테스트 엔진 + 성과지표
  backtest/walkforward.py  워크포워드 검증 (과최적화 여부 확인)
  risk/manager.py          포지션 사이징, 손절, 일일 손실 한도(kill switch)
  notify/discord.py        디스코드 웹훅 알림
  live/trader.py           실시간 매매 루프 (paper/live 공용)
  live/statelog.py         체결/자산 스냅샷 공용 로그 (대시보드가 읽는 소스)
  dashboard/app.py         실시간 모니터링 대시보드 (Flask)
  cli.py                   명령행 진입점
tests/                     pytest 단위 테스트
```

## 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example .env   # 필요한 키 입력 (아래 참고)
```

### 업비트 API 키 발급 (실계좌 매매 시에만 필요)

1. https://upbit.com/mypage/open_api_management 접속
2. Open API 키 발급 — **자산조회 + 주문** 권한 체크, IP 등록 필수
3. `.env` 에 `UPBIT_ACCESS_KEY`, `UPBIT_SECRET_KEY` 입력

백테스트와 페이퍼 트레이딩은 공개 시세 API만 쓰므로 키 없이 바로 동작합니다.

### 디스코드 웹훅

디스코드 채널 설정 → 연동 → 웹훅 만들기 → URL을 `.env` 의 `DISCORD_WEBHOOK_URL` 에 입력.
비워두면 알림이 콘솔 로그로 출력됩니다.

## 사용법

### 1. 데이터 수집

```bash
python -m quant.cli collect
```

`config.yaml` 의 `markets`(기본 KRW-BTC, KRW-ETH)에 대해 `data.days`(기본 730일)만큼
일봉을 수집해 `data/quant.db` 에 캐시합니다.

### 2. 전략 비교 (백테스트)

```bash
python -m quant.cli compare
```

`config.yaml` 의 `strategies` 그리드에 정의된 모든 (코인 × 전략 × 파라미터) 조합을
백테스트하고 buy&hold 대비 성과(총수익률/CAGR/MDD/샤프비율/승률)를 표로 출력합니다.
샤프비율 상위 조합이 하단에 별도로 요약됩니다. **이 결과를 보고 실전 투입 전략과
파라미터를 `config.yaml` 의 `live.strategy` / `live.params` 에 반영하세요.**

단일 조합만 보려면:

```bash
python -m quant.cli backtest --strategy volatility_breakout --market KRW-BTC --param k=0.5
```

### 3. 워크포워드 검증 (과최적화 확인 — compare 다음, paper 이전에 필수)

```bash
python -m quant.cli walkforward
```

`compare` 는 전체 과거 구간에서 가장 성과가 좋은 파라미터를 찾는데, 이는 과거
데이터에 우연히 맞춰진(curve-fitting) 결과일 수 있습니다. 워크포워드는
`config.yaml` 의 `walkforward.train_days`(기본 365일) 구간에서만 파라미터를
고르고, 그 다음 `test_days`(기본 90일) — **파라미터 선택에 전혀 쓰이지 않은
구간** — 에서의 성과(OOS, Out-Of-Sample)만 집계합니다. 이 창을 뒤로 밀며
반복해 여러 폴드의 OOS 성과를 봅니다.

출력의 "OOS 평균수익률"과 "수익 폴드 비율"을 확인하세요. `compare`의 전체구간
성과보다 OOS 성과가 크게 낮거나, 수익 폴드 비율이 낮다면(예: 50% 미만) 그
전략/파라미터는 과최적화되었을 가능성이 높으므로 실전 투입을 재고해야 합니다.

### 4. 페이퍼 트레이딩 (가상 자금, 필수 검증 단계)

```bash
python -m quant.cli paper
```

실시간 시세로 가상 체결하며 `config.yaml` 의 `live.strategy`/`live.params` 를 그대로
사용합니다(paper→live 전환 시 로직 차이가 없도록). 가상 잔고/거래내역은 `data/quant.db`
에 기록됩니다. **최소 2~4주 이상 운용해 실전 성과와 시그널 빈도를 확인한 뒤** 라이브로
전환하는 것을 권장합니다.

트레이더를 실행한 상태에서 별도 터미널에 아래를 실행하면 실시간 모니터링
대시보드를 볼 수 있습니다:

```bash
python -m quant.dashboard.app --mode paper --port 5000
# 브라우저에서 http://127.0.0.1:5000 접속 (15초마다 자동 새로고침)
```

현금/총자산/평가손익 요약, 자산 추이 그래프, 보유 포지션, 최근 체결 20건을
보여줍니다. 실계좌 모드는 `--mode live` (마찬가지로 `.env`의 업비트 API 키 필요).

### 5. 실계좌 자동매매

이중 안전장치가 있어 아래 둘 다 충족해야 실주문이 나갑니다:

1. `config.yaml` 의 `live.live_enabled: true`
2. CLI에 `--live` 플래그

```bash
python -m quant.cli live --live
```

### 리스크 관리 (config.yaml `risk` 섹션)

- `max_alloc_pct`: 코인 1개당 최대 자본 배분 비율
- `stop_loss_pct`: 진입가 대비 손실률 도달 시 강제 손절
- `daily_loss_limit_pct`: **하루 누적 실현손실이 이 비율을 넘으면 당일 신규 매수 중단**
  (kill switch) — 다음날 자동 해제
- `min_order_krw`: 업비트 최소 주문 금액(5,000원) 미만이면 주문 스킵

## 테스트

```bash
pytest
```

전략 시그널 로직, 백테스트 손익 계산, 워크포워드 검증, 리스크 매니저(kill switch
포함), 페이퍼 거래소 체결 로직, 대시보드 렌더링을 검증합니다.

## 한국주식(KIS) 확장

`src/quant/exchange/kis_stub.py` 에 `ExchangeAdapter` 인터페이스 스텁이 있습니다.
전략/백테스트/리스크/트레이더 코드는 거래소 구현과 무관하게 동작하므로, 이 스텁의
메서드(`get_ohlcv`, `buy_market`, `sell_market` 등)를 한국투자증권 KIS Developers
Open API로 구현하면 동일한 전략을 국내주식에도 그대로 적용할 수 있습니다.
필요한 사전 준비: KIS Developers 앱 등록(`KIS_APP_KEY`/`KIS_APP_SECRET`), 계좌 연동.

## 알려진 한계

- 백테스트는 일봉 종가 체결로 근사합니다(장중 슬리피지는 `slippage_pct` 로만 반영).
- 과거 성과가 미래 수익을 보장하지 않습니다. `walkforward` 명령으로 과최적화 여부를
  꼭 확인하세요 — 그래도 미래에 새로 등장하는 시장 상황(과거에 없던 패턴)까지
  방어해주지는 못합니다.
- 실행 환경은 로컬/직접 실행을 전제로 합니다. 24시간 무인 운영을 위해서는 별도의
  상시 구동 서버(예: 클라우드 VPS)와 프로세스 재시작 정책이 필요합니다.
