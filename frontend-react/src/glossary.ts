export type GlossaryEntry = {
  term: string;
  short: string;
  detail: string;
  tags?: string[];
};

export const GLOSSARY: GlossaryEntry[] = [
  {
    term: 'SMA5',
    short: '최근 5개 봉 평균 가격(단기 평균)',
    detail:
      'SMA5는 최근 5개 봉의 종가 평균입니다. 이 시스템에서는 “단기 평균으로 되돌림(Mean Reversion)” 목표(TP1)로 사용합니다.',
    tags: ['SMA', '평균', 'TP1'],
  },
  {
    term: 'SMA200',
    short: '최근 200개 봉 평균 가격(장기 추세)',
    detail:
      'SMA200은 최근 200개 봉의 종가 평균입니다. 장기 추세(상승/하락)를 판단하는 필터로 사용합니다. 예) 가격이 SMA200 위면 롱 우위.',
    tags: ['SMA', '추세', '레짐'],
  },
  {
    term: 'RSI(2)',
    short: '초단기 과매도/과매수 지표(2개 봉 기준)',
    detail:
      'RSI(2)는 아주 짧은 기간(2개 봉)의 상승/하락 강도를 보고 과매도/과매수를 판단합니다. 이 시스템에서는 롱은 RSI≤5, 숏은 RSI≥95 근처를 “과열/과매도” 신호로 사용합니다.',
    tags: ['RSI', '모멘텀'],
  },
  {
    term: 'ATR(14)',
    short: '변동성 지표(14개 봉 기준)',
    detail:
      'ATR(14)는 최근 14개 봉에서 가격이 얼마나 흔들렸는지(평균 진폭)를 나타냅니다. Entry/Stop은 ATR 배수로 거리(폭)를 잡습니다.',
    tags: ['ATR', '변동성'],
  },
  {
    term: 'ATR%',
    short: 'ATR을 현재가로 나눈 변동성 비율',
    detail:
      'ATR% = ATR / 현재가 × 100. 변동성이 너무 낮으면 움직임이 부족하고, 너무 높으면 리스크가 커지므로 “대기”/페널티에 사용합니다.',
    tags: ['ATR', '변동성'],
  },
  {
    term: 'MDD',
    short: '최대 낙폭(최고점 대비 최대 하락폭)',
    detail:
      'MDD(Max Drawdown)는 백테스트/운용 중 자산이 최고점 대비 얼마나 크게 하락했는지의 최대값입니다. 낮을수록 안정적입니다.',
    tags: ['백테스트', '리스크'],
  },
  {
    term: 'Fill rate',
    short: '지정가 체결 비율',
    detail:
      'Limit(지정가) 진입을 썼을 때 실제로 체결된 비율입니다. 낮으면 신호는 나와도 주문이 잘 안 채워져 실전 성과가 달라질 수 있습니다.',
    tags: ['체결', '지정가'],
  },
  {
    term: 'R:R',
    short: '손익비(손절 대비 목표수익 비율)',
    detail:
      'R:R(Reward:Risk)는 손절폭(리스크) 대비 목표수익이 얼마나 되는지 나타냅니다. 예) 1.5는 손절 1 대비 이익 1.5를 목표.',
    tags: ['리스크', '손익비'],
  },
  {
    term: 'Score',
    short: '진입 용이성 점수(현재 조건과의 근접도)',
    detail:
      'Score는 “지금 진입하기 쉬운가”를 나타냅니다. 트리거가 이미 충족되면 높고, 아직 멀면 낮습니다.',
    tags: ['스코어'],
  },
  {
    term: 'Comp',
    short: '복합 점수(진입 용이성 + 백테스트 + 레짐 등)',
    detail:
      'Comp는 후보 TF를 고르기 위한 최종 점수입니다. 진입 용이성, 최근 백테스트 점수, 1D 레짐, 변동성 조건 등을 합쳐 계산합니다.',
    tags: ['스코어'],
  },
  {
    term: 'Conf',
    short: '추천 신뢰도(0~100)',
    detail:
      'Conf는 현재 후보가 얼마나 “괜찮아 보이는지”를 0~100으로 요약한 값입니다. 진입 용이성/백테스트/레짐 등을 반영합니다.',
    tags: ['스코어'],
  },
  {
    term: 'BT',
    short: '최근 백테스트 점수(정규화)',
    detail:
      'BT는 최근 구간의 백테스트 점수를 0~1로 눌러 담아 비교한 값입니다. 높을수록 최근 성과(수익/낙폭 균형)가 상대적으로 좋습니다.',
    tags: ['백테스트'],
  },
  {
    term: 'Regime',
    short: '1D 장기 추세(롱/숏 우위)',
    detail:
      'Regime은 1D에서 SMA200 대비 현재가 위치로 장기 추세를 분류합니다. 레짐과 반대 방향은 보수적으로 평가합니다.',
    tags: ['레짐', 'SMA200'],
  },
];

export function findGlossary(term: string): GlossaryEntry | undefined {
  const needle = term.trim().toLowerCase();
  if (!needle) return undefined;
  return GLOSSARY.find((g) => g.term.toLowerCase() === needle);
}
