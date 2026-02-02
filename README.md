# Wonyodd Reco Site (TradingView webhook → 추천 UI)

트레이더가 **LONG/SHORT만 선택**하면,
서버가 **1D(일봉) 레짐(SMA200)**을 참고하고,
**30m / 60m / 180m** 중에서 **진입이 가장 용이한 타임프레임 1개**를 자동 선택해
**Entry / Stop / TP / 권장 최대 배율**을 안내합니다.

> 이 패키지는 *보조지표 데이터 없이도* OHLC만으로 동작합니다.  
> (원하면 TradingView에서 추가 지표 값을 `features`로 같이 보내 저장할 수 있습니다.)

---

## 1) 빠른 설치 (Ubuntu)

```bash
unzip wonyodd_reco_site.zip
cd wonyodd_reco_site
bash install.sh
```

설치 후:
- 웹: `http://YOUR_SERVER_IP:8010/`
- 추천 API: `GET http://YOUR_SERVER_IP:8010/api/recommend?side=long`
- 웹훅: `POST http://YOUR_SERVER_IP:8010/api/webhook/tradingview`

---

## 2) 환경변수(권장)

`/opt/wonyodd-reco/.env`에서 설정:

- `WONYODD_WEBHOOK_SECRET`: 웹훅 비밀키 (TradingView payload의 `password` 혹은 헤더 `X-Webhook-Secret`로 전달)
- `WONYODD_DB_PATH`: sqlite 경로
- `WONYODD_RISK_PCT_DEFAULT`: 트레이드당 계좌 리스크(%) 기본값 (예: 0.5)
- `WONYODD_MAX_LEVERAGE`: 최대 추천 배율 상한
- `WONYODD_ENTRY_ATR_K_30`, `WONYODD_ENTRY_ATR_K_60`, `WONYODD_ENTRY_ATR_K_180`: TF별 ATR 진입 배수
- `WONYODD_STOP_ATR_MULT`: ATR 손절 배수

---

## 3) 초기 데이터 적재(선택)

이미 가진 CSV(1D/30/60/180)를 DB에 넣으면, 웹훅이 오기 전에도 추천이 가능합니다.

```bash
source /opt/wonyodd-reco/venv/bin/activate
python /opt/wonyodd-reco/backend/tools/import_csv.py --csv "/path/to/OKX_BTCUSDT.P, 1D.csv" --timeframe 1D
python /opt/wonyodd-reco/backend/tools/import_csv.py --csv "/path/to/OKX_BTCUSDT.P, 30.csv" --timeframe 30m
python /opt/wonyodd-reco/backend/tools/import_csv.py --csv "/path/to/OKX_BTCUSDT.P, 60.csv" --timeframe 60m
python /opt/wonyodd-reco/backend/tools/import_csv.py --csv "/path/to/OKX_BTCUSDT.P, 180.csv" --timeframe 180m
sudo systemctl restart wonyodd-reco
```

CSV 포맷은 최소한 `time, open, high, low, close, volume` 컬럼이 있으면 동작합니다.

---

## 4) TradingView Alert JSON 예시

Webhook URL: `http://YOUR_SERVER_IP:8010/api/webhook/tradingview`

Message:

```json
{
  "password": "YOUR_SECRET_OPTIONAL",
  "exchange": "{{exchange}}",
  "symbol": "{{ticker}}",
  "timeframe": "{{interval}}",
  "time": "{{time}}",
  "open": "{{open}}",
  "high": "{{high}}",
  "low": "{{low}}",
  "close": "{{close}}",
  "volume": "{{volume}}",
  "features": {
    "rsi14": "{{rsi}}"
  }
}
```

---

## 5) 설계 메모

- 1D 레짐:
  - `1D close > 1D SMA200` → long_favored
  - `1D close < 1D SMA200` → short_favored
- 진입 용이성 점수(entry_ease_score):
  - 트리거 충족이면 100점 부여
  - 미충족이면 `SMA5 거리 + RSI 임계치 거리`로 감점
  - 레짐과 방향이 맞으면 가산(+10), 반대면 감점(-25)

추천 가격은 **ATR 기반 지정가**:
- LONG: `entry = close - k*ATR14`, `stop = entry - 1.5*ATR14`, `tp1 = SMA5`
- SHORT: `entry = close + k*ATR14`, `stop = entry + 1.5*ATR14`, `tp1 = SMA5`

권장 최대 배율:
- `max_leverage = min(MAX_LEVERAGE, risk_pct / stop_pct)`
- stop_pct = 손절폭(%)
