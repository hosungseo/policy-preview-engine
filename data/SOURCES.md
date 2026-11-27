# 데이터 출처 (data/SOURCES.md)

이 저장소의 코드는 Apache License 2.0을 따릅니다(`LICENSE`, `NOTICE`). 아래 데이터 파일은 각자의 출처와 이용 조건을 따르며, Apache License로 다시 허락하지 않습니다. 다시 쓰거나 나눠 줄 때는 표의 출처를 함께 밝혀 주세요.

- 합성 인물이 들어 있는 파일은 NVIDIA **Nemotron-Personas-Korea**(CC BY 4.0, https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea)에서 왔습니다. 인물 이름과 서술은 실존 인물이 아닙니다.
- 공공 통계는 KOSIS(국가통계포털) 등에 공개된 표를 출처 표기 조건으로 씁니다. 표 ID는 각 파일 안(`source`, `sources`, `sources_detail`)에 적어 두었습니다.
- "이 프로젝트 생성"은 이 저장소의 코드로 만든 값입니다. 판단 모델(TypeSafe Jev)과 문장 모델(Claude)의 출력이 들어 있으며, 실제 여론이 아닙니다.
- 엔진이 새로 만드는 결과 JSON(실행 묶음, 계획서, 조사 결과, 찾아갈 곳 카드, 100만 명 지도 `meta.json`, 패널 묶음의 `.meta.json`)에는 이 표의 요약인 `attribution` 항목이 함께 들어갑니다. 합성 인물의 CC BY 4.0 표시, 원본 revision, 가공 내용, 그 결과에 쓴 공공 통계 이름이 담기므로 파일 하나만 옮겨도 출처가 따라갑니다(`engine/pp/attribution.py`).
- 저장소 루트의 `data/` 폴더에는 이 파일만 git에 올립니다. 합성 인물 원본 내려받기(`data/nemotron-personas-korea/`)와 캐시는 올리지 않습니다.

## 표

의미 검색 기본값은 `intfloat/multilingual-e5-large`(MIT, XLM-RoBERTa 기반)입니다. `data/emb/multilingual-e5-large-v1/`는 원본 인물 서술(CC BY 4.0)에서 **새로 계산 필요**하며 저장소에 배포하지 않습니다. 기존 사전 계산 임베딩과 호환되지 않습니다. 만드는 명령과 모델 revision은 [임베딩 안내](../docs/embeddings.md)에 있습니다.

`web/public/runs/`의 기존 예시 4건은 이전 검색 구성으로 영향권 인물을 고른 보관 결과입니다. 새 모델로 재계산한 결과가 아니며, 검색 단계까지 새 모델로만 만든 예시로 사용하려면 패널 선택 이후 결과를 다시 생성해야 합니다. 이 변경에서 원본 인물 데이터나 이전 판단 결과를 다른 모델이 만든 것으로 바꾸어 표시하지 않았습니다.

| 파일(또는 폴더) 경로 | 내용 | 출처 | 라이선스·이용 조건 | 만든 방법 |
|---|---|---|---|---|
| `engine/ppservice/data/persona-accuracy/sources.json`, `sources-reviewed.json` | 정확도 비교에 쓴 공표 표 목록과 검토 상태 | 통계청 「2024 사회조사」(KOSIS DT_1SSFA060R, DT_1SSFA080R, DT_1SSSA020R, DT_1SSSA012R, DT_1SSSA011R), 행정안전부 주민등록인구현황(KOSIS DT_1B04005N) | KOSIS 이용 조건(출처 표기) | `sources-reviewed.json`: `engine/scripts/prepare_measured_baseline.py` / `sources.json`: 손으로 작성한 이전 판 목록 |
| `engine/ppservice/data/persona-accuracy/benchmark-v2.json`, `mapping-v1.json`, `reference-2024.json`, `schema-v2.json` | 정확도 비교 문항 정의·대응표·기준 틀·JSON 스키마 | 문항 문구는 통계청 「2024 사회조사」 조사표, 나머지는 이 프로젝트 작성 | 문항 문구: KOSIS·통계청 출처 표기 / 나머지: Apache-2.0 | 손으로 작성한 계약 파일(생성 스크립트 없음) |
| `engine/ppservice/data/persona-accuracy/comparison-2024.json`, `comparison-2024-reversed.json`, `measured-run.json`, `historical-baseline-2024.json` | 합성 패널 성인 응답과 공표 분포의 비교(정순·역순), 실행 기록(호출 수·토큰·비용), 묶음 해시 | 위 공표 표 + Nemotron-Personas-Korea 패널 + 이 프로젝트 생성(TypeSafe Jev 응답, 2026-10-27) | 공표 분포: KOSIS 출처 표기 / 인물: CC BY 4.0 / 나머지: Apache-2.0 | `engine/scripts/run_measured_baseline.py`, `promote_measured_baseline.py` |
| `engine/ppservice/data/persona-accuracy/holdout-2026-11-10.json` | 판단 모델 3개(TypeSafe Jev, Upstage Solar Decide, tev1:4b)로 잰 「2024 사회조사」 10문항 비교 기록 | 통계청 「2024 사회조사」(KOSIS), 주민등록 연령대 인구 가중 + 이 프로젝트 생성(모델 응답, 2026-11-10) | 공표 분포: KOSIS 출처 표기 / 나머지: Apache-2.0 | 서비스 지시문 그대로 측정한 결과를 기록(측정용 스크립트는 저장소에 없음) |
| `engine/ppservice/data/persona-accuracy/README.md` | 위 기록을 읽을 때의 제한 | 이 프로젝트 작성 | Apache-2.0 | 손으로 작성 |
| `engine/ppservice/data/persona-context/addons-v1.json`, `addons-v2.json` | 기본 인물에 덧붙이는 생활 여건 항목 정의와 표별 출처 목록 | 공공 통계(아래 「공공 통계 목록」, 표 ID는 파일의 `sources_detail`) | KOSIS 등 출처 표기 | `engine/scripts/build_life_context.py`(v2). v1은 이전 판 기록 |
| `engine/ppservice/data/persona-context/report-v1.json`, `report-v2.json` | 생활 여건 배정 결과를 공식 분포와 견준 검증 보고 | 위 공공 통계 + Nemotron-Personas-Korea 패널 | 공공 통계: 출처 표기 / 인물 집계: CC BY 4.0 | `engine/scripts/build_life_context.py`(v2). v1은 이전 판 기록 |
| `engine/ppservice/data/persona-context/report-history-v1.json` | 생애 이력(2017~2025)과 2030 전망 가정·검증 보고 | 소득이동통계, 일자리행정통계, 경제활동인구조사, 인구이동통계, 인구동향, 간이생명표(2024), 지역사회건강조사(KOSIS) + Nemotron 패널 | KOSIS 출처 표기 / 인물 집계: CC BY 4.0 | `engine/scripts/build_life_history.py` |
| `engine/series/official/census2020_tenure.json` | 시군구별 점유형태 분포 | 통계청 2020 인구주택총조사(표본), KOSIS DT_1PE2006·DT_1PE2010·DT_1PR2008 | KOSIS 출처 표기 | `engine/scripts/fetch_kosis_housing.py` |
| `engine/series/official/ownership2024.json` | 시군구별 주택 소유·다주택·주택자산가액 구간 | 통계청 2024 주택소유통계, KOSIS DT_1OH0402·DT_1OH0407·DT_1OH0410 | KOSIS 출처 표기 | `engine/scripts/fetch_kosis_housing.py` |
| `engine/series/official/housing_market.json` | 대책 발표 전 3개월 시군구 실거래 요약(매매·전세·월세 중위 등) | 국토교통부 실거래가 자료 8종(아래 「국토교통부 실거래가 자료」 행) | 이용허락범위 제한 없음(아래 「국토교통부 실거래가 자료」 행) | `engine/scripts/fetch_rtms.py` → `build_housing_market.py`(원자료는 올리지 않고 요약값만) |
| `engine/series/official/tenure.json` | 2024년 시도별 자가·임차·무상 비율 | 국토교통부 「2024년도 주거실태조사」, 국토교통 통계누리 표(형식 6909), 2026-09-25 조회 | 출처 표기 | 통계누리 표 값을 비율로 옮김(파일의 `note`) |
| `engine/series/official/regions.json` | 인물의 시군구 → 법정동 시군구 코드·KOSIS 지역 코드 대응 | 행정안전부 법정동코드(StanReginCd API), KOSIS DT_1PE2010·DT_1OH0402 | 출처 표기 | `engine/scripts/build_region_codes.py` |
| `engine/series/official/persona_context.json` | 시군구·성·연령별 배정 확률표(생활 여건) | 공공 통계(아래 목록, 표 ID는 파일의 `sources`) | KOSIS 등 출처 표기 | `engine/scripts/fetch_persona_context.py` → `build_persona_context.py` |
| `engine/series/housing.json` | 부동산 대책 10건의 본문과 조항 나눔 | 정책브리핑(korea.kr) 7건: 아래 「정책브리핑 원문 출처 표시」 표의 기사·보도자료 원문 / 금융위원회(fsc.go.kr) 보도자료 3건(2025-06-27, 2026-04-01, 2026-08-13): 원문 대신 이 저장소가 쓴 요약(`source.text_kind`가 `summary`) | 정책브리핑 원문: 공공누리 제1유형(출처표시), 텍스트에 한함 / 금융위원회 3건: 기사별 공공누리 표시가 없어 원문을 싣지 않음, 요약문은 Apache-2.0, 원문은 링크로만 | 정책브리핑 원문: `engine/scripts/fetch_press.py`(원문과 다시 대조: `fetch_press.py verify`, 요약 3건은 건너뜀) / 요약: 손으로 새로 씀 |
| `engine/series/regulated_areas.json` | 발표일 기준 투기과열지구·조정대상지역 기간 3개와 근거 문장 | 정책브리핑(korea.kr) 「주택시장 안정화 대책」 발표·「'동탄·기흥·구리' 3곳 투기과열지구·조정대상지역 지정」 원문 문장, 금융위원회 2025-06-27 보도자료는 이 저장소의 요약 한 문장(`kind`가 `summary`) | 정책브리핑 문장: 공공누리 제1유형(출처표시) / 금융위원회: 원문 문장을 싣지 않음, 요약은 Apache-2.0 | 출처 문서의 문장을 옮기거나 요약해 기간을 정리(파일의 `note`, 생성 스크립트는 저장소에 없음) |
| `engine/policies/life-safety-decree.json`, `elderly-welfare-rule.json` | 입법예고문의 제정·개정 이유와 주요내용 원문 | 국민참여입법센터 입법예고(행정안전부 88826, 보건복지부 89004) | 국가의 공고문(저작권법 제7조의 보호받지 못하는 저작물), 출처 URL 기록 | 원문을 그대로 옮김 |
| `engine/policies/rural-basic-income.json` | 농어촌 기본소득 시범사업 요약 | 농림축산식품부 보도자료(2026.5.)와 추가 선정 보도(2026.6.11.) | 요약문: Apache-2.0 / 원문: 출처 URL 기록 | 이 프로젝트가 요약해 작성 |
| `engine/policies/judge-attendance.json`, `subway-free-ride.json` | 시연용 가상 정책안(정부 발표 아님) | 이 프로젝트 작성(공개 논의를 바탕으로 함) | Apache-2.0 | 손으로 작성 |
| `web/public/runs/*.json`(4건)과 `index.json` | 위 정책 4건의 예시 실행 결과: 대표 300명·영향권 100명의 반응, 쟁점, 판단 결과, 가상 공청회, 계획서 초안 | Nemotron-Personas-Korea 인물 + 이 프로젝트 생성(문장: Claude `claude -p` haiku·sonnet, 판단: TypeSafe Jev, 2026-09-23~24) + 위 정책 문안 | 인물 서술: CC BY 4.0 / 생성 결과: Apache-2.0 / 정책 문안: 위 각 행 | `python -m pp run` → `python -m pp export` |
| `web/public/series/housing.json` | 부동산 대책 흐름: 합성 인물 1만 명 × 대책 10건 × 2조건 응답 요약, 대책 본문, 지역 실거래 예시 | Nemotron-Personas-Korea 인물 + 이 프로젝트 생성(TypeSafe Jev, 2026-09-25) + `engine/series/` 입력(본문은 위 `engine/series/housing.json` 행과 같음) + 실거래가(아래 「국토교통부 실거래가 자료」 행) + 공공 통계 | 인물 집계: CC BY 4.0 / 생성 결과: Apache-2.0 / 본문: 위 각 행 / 실거래가: 이용허락범위 제한 없음 | `python -m pp series engine/series/housing.json --housing …`. 금융위원회 3건은 응답을 받을 때 원문 발췌를 보여 줬고, 저장소에는 요약만 남김 |
| `web/public/series/housing-map/meta.json` | 100만 명 지도 설정, 시도·서울 경계선(단순화), 시군구 목록, 대책별 평균 | 행정구역 경계: 국토교통부 행정구역도(브이월드 2D 데이터 API 2.0, `LT_C_ADSIDO_INFO`·`LT_C_ADSIGG_INFO`·`LT_C_ADEMD_INFO`, 2026-04-23 기준) + Nemotron-Personas-Korea + 이 프로젝트 생성 | 경계: 공공누리 제1유형(출처표시), 공공데이터포털 「국토교통부_행정구역도(WMS/WFS)」(15059008) 표시 기준 / 인물 집계: CC BY 4.0 | `python -m pp peoplemap` |
| `web/public/series/housing-map/dots.bin`, `panel.bin` | 합성 인물 100만 명의 점 위치(시군구까지만 실제, 읍면동 안은 넓이 비례로 흩음)와 1만 명 패널의 점유형태·답 | Nemotron-Personas-Korea(시군구) + 위 행정구역도 경계(읍면동 넓이) + 이 프로젝트 생성(TypeSafe Jev) | 인물: CC BY 4.0 / 경계: 공공누리 제1유형 / 생성 결과: Apache-2.0 | `python -m pp peoplemap` |
| `web/public/series/housing-map/people-00.json` ~ `people-19.json` | 지도에서 점을 누를 때 보이는 1만 명의 인물 카드(나이·직업·가구·주거·서술 한 줄)와 대책별 답 | Nemotron-Personas-Korea 인물 서술 + 이 프로젝트 생성(TypeSafe Jev) | 인물 서술: CC BY 4.0 / 생성 결과: Apache-2.0 | `python -m pp peoplemap` |
| 국토교통부 실거래가 자료 (공공데이터포털 오픈API 8종, 원자료는 저장소에 없음) | 「부동산 거래신고 등에 관한 법률」에 따라 신고된 매매·전월세 거래 | 제공기관 국토교통부, 공공데이터포털: 「국토교통부_아파트 매매 실거래가 자료」 https://www.data.go.kr/data/15126469/openapi.do · 「국토교통부_아파트 전월세 실거래가 자료」 https://www.data.go.kr/data/15126474/openapi.do · 「국토교통부_연립다세대 매매 실거래가 자료」 https://www.data.go.kr/data/15126467/openapi.do · 「국토교통부_연립다세대 전월세 실거래가 자료」 https://www.data.go.kr/data/15126473/openapi.do · 「국토교통부_단독/다가구 매매 실거래가 자료」 https://www.data.go.kr/data/15126465/openapi.do · 「국토교통부_단독/다가구 전월세 실거래가 자료」 https://www.data.go.kr/data/15126472/openapi.do · 「국토교통부_오피스텔 매매 실거래가 자료」 https://www.data.go.kr/data/15126464/openapi.do · 「국토교통부_오피스텔 전월세 실거래가 자료」 https://www.data.go.kr/data/15126475/openapi.do | **이용허락범위 제한 없음**, 무료(8종 모두 포털 표시, 2026-11-27 확인) | `engine/scripts/fetch_rtms.py`(서비스 이름 RTMSDataSvcAptTrade·AptRent·RHTrade·RHRent·SHTrade·SHRent·OffiTrade·OffiRent). 이 자료를 쓰는 공개 파일: `engine/series/official/housing_market.json`, `web/public/series/housing.json` |

테스트가 쓰는 인물·정책은 테스트 코드 안에서 합성으로 만들며, 따로 둔 데이터 파일은 없습니다.

## 정책브리핑 원문 출처 표시

아래 기사·보도자료의 텍스트는 원래 페이지에 「이 자료는 텍스트에 한하여 공공누리 제1유형(출처표시)의 조건에 따라 이용할 수 있습니다」라고 표시되어 있습니다(2026-11-27 확인). 사진·이미지는 이 저장소에 넣지 않았습니다. 첨부 파일(HWPX·PDF)에서 옮긴 본문은 그 첨부가 달린 페이지의 표시를 따릅니다.

| 기사 제목 | 제공 | 주소 | 이용 조건 | 쓰는 곳 |
|---|---|---|---|---|
| 외국인 토지거래허가구역 지정 관련 | 국토교통부(정책브리핑) | https://www.korea.kr/briefing/policyBriefingView.do?newsId=156721754 | 공공누리 제1유형 | 대책 2025-08-21 본문 |
| 새정부 「주택공급 확대방안」 발표 | 국토교통부(정책브리핑) | https://www.korea.kr/briefing/pressReleaseView.do?newsId=156713255 | 공공누리 제1유형 | 대책 2025-09-07 본문 |
| 「주택시장 안정화 대책」 발표 | 국토교통부(정책브리핑) | https://www.korea.kr/briefing/pressReleaseView.do?newsId=156718969 | 공공누리 제1유형 | 대책 2025-10-15 본문, 규제지역 2025-10-16 근거 문장 |
| 도심 주택공급 확대 및 신속화 방안 발표 | 국토교통부(정책브리핑) | https://www.korea.kr/briefing/policyBriefingView.do?newsId=156742030 | 공공누리 제1유형 | 대책 2026-01-29 본문 |
| 외국인등 부동산 투기방지를 위해 거래신고 강화한다. | 국토교통부(정책브리핑) | https://www.korea.kr/briefing/pressReleaseView.do?newsId=156743690 | 공공누리 제1유형 | 대책 2026-02-09 본문 |
| '동탄·기흥·구리' 3곳 투기과열지구·조정대상지역 지정 | 국토교통부(정책브리핑 정책뉴스) | https://www.korea.kr/news/policyNewsView.do?newsId=148967354 | 공공누리 제1유형 | 대책 2026-06-30 본문, 규제지역 2026-07-01 근거 문장 |
| 거주용 1주택, 시가 20억 원까지 종부세 과세 대상서 제외 | 정책브리핑(정책뉴스) | https://www.korea.kr/news/policyNewsView.do?newsId=148969278 | 공공누리 제1유형 | 대책 2026-08-03 본문 |

금융위원회 보도자료 3건(https://www.fsc.go.kr/no010101/84824, /86606, /87517)은 기사별 공공누리 표시가 없고, 금융위원회 저작권정책은 수익 목적 이용에 사전 협의를 요구합니다. 그래서 원문을 싣지 않고 제목·링크와 이 저장소가 새로 쓴 요약만 둡니다.


## 공공 통계 목록

파일에 들어 있는 공공 통계의 이름입니다(작성기관·조사명 기준). 표 ID는 각 파일 안에 있습니다.

- 통계청(국가데이터처): 2024 사회조사, 인구주택총조사(2005·2015·2020), 2024 주택소유통계, 경제활동인구조사(근로형태별 부가조사 포함), 지역별고용조사, 연금통계, 소득이동통계, 일자리행정통계, 인구이동통계, 인구동향, 2024 간이생명표
- 통계청·금융감독원·한국은행: 가계금융복지조사
- 행정안전부: 주민등록인구현황, 법정동코드
- 보건복지부: 등록장애인 현황, 국민기초생활보장 수급자 현황, 노인실태조사(2023)
- 질병관리청: 지역사회건강조사, 국민건강영양조사
- 국민연금공단: 노령연금 수급자 현황
- 과학기술정보통신부·한국지능정보사회진흥원: 스마트폰 과의존 실태조사, 디지털정보격차 실태조사
- 문화체육관광부: 국민독서실태조사, 문화향수실태조사, 국민여가활동조사 계열 자원봉사 참여, 해외여행 경험률
- 농림축산식품부: 반려동물 양육 실태조사
- 한국행정연구원: 사회통합실태조사(2025)
- 한국보건사회연구원·국민건강보험공단: 한국의료패널(2023)
- 안전보건공단: 제7차 근로환경조사(2023)
- 국무조정실: 청년 삶 실태조사(2024)
- 경찰청: 운전면허 소지자 현황(2024)
- 고용노동부: 고용형태별 근로실태조사(2025)
- KOSIS 기관 코드 164: 2025 디지털 역량(키오스크 이용) 조사
- 국토교통부: 2024년도 주거실태조사(국토교통 통계누리), 실거래가 공개자료(공공데이터포털), 행정구역도(브이월드)
