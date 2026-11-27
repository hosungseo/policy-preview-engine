# Nemotron 원본 다운로드 revision 확인

확인일: 2026-11-27. 원본 저장소: `nvidia/Nemotron-Personas-Korea` (CC BY 4.0).

**실제로 내려받은 revision: `ada0f5b53a38bb5a30cce09358adde883c1ab63a`**.
확인 시점의 최신판을 과거판 대신 기입한 값이 아니다. 기록 상태는 `verified_local_download`다.

## 근거

- `~/policy-preview/data/vendor/korean-people-persona/.cache/huggingface/download/data/train-0000{0..8}-of-00009.parquet.metadata` 9개 모두 첫 줄에 같은 commit SHA가 있다. 다운로드 시각은 2026-09-23 14:32:55~14:42:47 UTC (23:32:55~23:42:47 KST)다.
- `~/policy-preview/data/hf/hub/datasets--nvidia--Nemotron-Personas-Korea/refs/main`도 같은 SHA다. 갱신 가능한 ref 하나만으로 판정하지 않고 파일별 다운로드 기록과 함께 확인했다.
- 위 vendor 캐시의 `trees/ada0f5b53a38bb5a30cce09358adde883c1ab63a.json`에 저장된 파일 크기·LFS SHA-256, 각 다운로드 메타데이터의 ETag, 현재 보관된 원본 parquet의 실제 SHA-256이 **9개 전부 일치**한다. 약 2GB 원본을 읽기만 했다.
- 기존 `panel-20k-full.jsonl.xz`의 **20,000명, 26개 원본 필드 전부**를 해당 parquet에서 uuid로 찾아 대조했다. 리스트 필드에는 기존 SQLite 변환기의 JSON 정규화 규칙을 적용했으며 모두 일치했다.
- 기존 `panel-20k.jsonl.gz`의 uuid·성별·나이·시도 및 20,000개 프로필도 전체 필드 파일에서 기존 `persona_profile` 규칙(이름 추출 포함)으로 계산한 값과 모두 일치했다. 패널 파일은 다시 쓰지 않았다.

기계 판독용 근거와 파일별 체크섬은 [nemotron-source-revision.json](nemotron-source-revision.json)에 있다. 재확인용 읽기 전용 스크립트는 로컬 `~/pp-public-release-notes/2026-11-27-verify-source.py`, 실행 로그는 같은 폴더의 `2026-11-27-source-verification.log`다.

## 적용 범위

이 확인은 위 두 **기존 원본 패널 파일**의 출처를 입증한다. 각각의 과거 실행이 어떤 모델판·애드온판·seed·패널 부분집합을 사용했는지까지 일괄 입증하지 않는다. 저장된 사례 JSON과 과거 실행 meta는 변경하지 않았고, 생활 여건 배정·이력·전망·사례 결과도 재생성하지 않았다. 향후 실행은 실제 입력 파일의 해시와 이 출처 기록을 함께 보존한다.

현재 코드는 다운로드할 HF revision을 먼저 commit SHA로 확정하고 패널·DB 옆 `<파일명>.meta.json`에 기록한다. 로컬 parquet으로 새로 만들 때는 위 SHA를 `--revision`에 명시한다. 기존 사례를 새 결과로 읽거나 metadata에 증거 없는 과거 실행 정보를 채우면 안 된다.

가구 연소득·부채·자동차·순자산의 사람 패널 배정은 기존 근사를 유지한다. 가구 연결키·정확한 가구원 수가 없어 개인 비율로 보정하지 않았으며, `finance_unit = household_to_person_approximation`과 `limitations`, README의 한계 표시도 유지했다.
