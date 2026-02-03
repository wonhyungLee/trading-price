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
- `WONYODD_MIN_ATR_PCT`, `WONYODD_MAX_ATR_PCT`: 변동성(ATR%) 허용 범위
- `WONYODD_REQUIRE_BAR_CLOSE`: true면 “봉 마감 알림”만 수용
- `WONYODD_VALIDATE_TS_ALIGNMENT`: true면 timeframe 정렬 timestamp만 수용
- `WONYODD_DISCORD_WEBHOOK_URL`: 디스코드 웹훅 URL(권장)
- `WONYODD_DISCORD_WEBHOOK_FILE`: 디스코드 웹훅이 들어있는 파일 경로(기본 `개인정보.txt`)
- `WONYODD_SPIKE_NOTIFY_ENABLED`: true면 “거래량+변동성 스파이크” 발생 시 자동으로 디스코드 알림 전송
- `WONYODD_SPIKE_NOTIFY_TFS`: 감지할 TF 목록(기본 `30m,60m,180m`)
- `WONYODD_SPIKE_NOTIFY_SIDE`: 추천 방향(기본 `auto` = long/short 둘 다 계산 후 더 유리한 쪽 선택). `long|short|auto`
- `WONYODD_SPIKE_NOTIFY_ONLY_BAR_CLOSE`: true면 봉 마감에서만 알림(권장)
- `WONYODD_SPIKE_NOTIFY_ONLY_READY`: true면 추천 상태가 READY일 때만 알림
- `WONYODD_SPIKE_NOTIFY_COOLDOWN_SEC`: 알림 쿨다운(초, 기본 300)
- `WONYODD_SPIKE_VOL_LOOKBACK`: 거래량 기준선 계산용 lookback bar 수(기본 20)
- `WONYODD_SPIKE_VOL_MULT`: 거래량 스파이크 배수(기본 3.0). 현재 거래량 >= (이전 N개 거래량 median) * 배수
- `WONYODD_SPIKE_RANGE_LOOKBACK`: 변동성 기준선 계산용 lookback bar 수(기본 20)
- `WONYODD_SPIKE_RANGE_MULT`: 변동성 스파이크 배수(기본 2.0). 현재 bar range% >= (이전 N개 range% median) * 배수
- `WONYODD_SPIKE_MIN_RANGE_PCT`: 변동성 최소 조건(기본 0.4%). range% = (high-low)/close*100

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
  "bar_close_confirmed": true,
  "features": {
    "rsi14": "{{rsi}}"
  }
}
```

---

## 5) TradingView 알림 권장 설정(30m/1h/3h)

* 30m/1h/3h 차트 각각 알림 생성
* 조건: `바 마감 시` (Once Per Bar Close)
* Webhook JSON에 `bar_close_confirmed: true` 포함

권장 메시지 필드:
- `timeframe`: `30`, `60`, `180`
- `time`: `{{time}}` (TradingView 기본 타임스탬프)
- `bar_close_confirmed`: `true`

---

## 6) 디스코드 알림

추천 결과를 디스코드로 전송:

- API: `POST /api/notify/recommend?side=long&risk_pct=0.5`
- 프론트: `디스코드 전송` 버튼

웹훅 URL 설정 방법:
- `.env`에 `WONYODD_DISCORD_WEBHOOK_URL` 지정(권장)
- 또는 `개인정보.txt` 파일 내 `https://discord.com/api/webhooks/...` 라인을 자동 탐지

---

## 7) 설계 메모

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
