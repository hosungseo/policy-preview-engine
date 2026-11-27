# 로컬 의미 검색과 인물 벡터 재계산

현재 의미 검색 기본값은 `intfloat/multilingual-e5-large`입니다. XLM-RoBERTa-large에서 초기화한 MIT 모델이며, 1024차원 벡터와 최대 512토큰을 사용합니다. 정확한 모델 revision은 `3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`로 고정했습니다. [공식 모델 카드](https://huggingface.co/intfloat/multilingual-e5-large)에 기반 모델·라이선스와 한국어에도 필요한 접두어가 설명돼 있습니다.

인물 임베딩은 **새로 계산 필요**합니다. 이전에 내려받은 100만 명 사전 계산 임베딩은 다른 모델의 결과이므로 새 모델의 질의 벡터와 섞지 않습니다. 벡터를 변환하거나 이름만 바꿔 복사할 수 없습니다. 원본 인물 데이터인 NVIDIA Nemotron-Personas-Korea(CC BY 4.0)는 그대로 사용할 수 있습니다.

새 파일은 `PP_DATA_DIR/emb/multilingual-e5-large-v1/` 아래에 저장합니다.

- `emb.f16.npy`: 이름을 제거한 원본 인물 서술에서 새로 계산한, 단위 정규화된 float16 행렬
- `emb_uuids.txt`: 행 순서와 같은 순서의 UUID
- `manifest.json`: 모델·revision·차원·텍스트 형식·정규화·완료 상태·행 수

파일과 manifest가 맞을 때만 의미 검색이 켜집니다. 이전 `emb/emb.f16.npy`와 parquet 임베딩 shard는 읽지 않습니다. 새 파일이 없으면 의미 검색을 생략하고 이유를 기록하며, 속성·FTS 검색을 계속 사용합니다. `PP_SEMANTIC=off` 또는 `PP_PERSONA_SOURCE=bundle`에서도 꺼집니다. Jev·tev1·Solar Decide와 local 프로필 설정은 이 변경의 대상이 아닙니다.

## 맥미니에서 실행할 명령

이 커밋의 작업 사본과 원본 인물 SQLite DB를 맥미니에 준비한 뒤, 아래 경로를 실제 경로로 바꿔 실행하세요. 로컬 CPU 또는 사용 가능한 Apple MPS를 쓰며 외부 추론 API를 호출하지 않습니다. 모델을 처음 받을 때는 Hugging Face에 연결합니다.

```sh
cd /path/to/policy-preview-engine
python3.12 -m venv .venv
.venv/bin/python -m pip install -e . -r engine/requirements-semantic.txt
export PP_DATA_DIR=/path/to/data
export PP_PERSONA_DB=/path/to/persona.db
# 먼저 소규모 속도 측정. 전체 인덱스를 활성화하지 않습니다.
.venv/bin/python engine/scripts/build_embeddings.py --limit 2000 --batch-size 16
# 출력된 pilot manifest의 personas_per_second로 예상 시간을 계산하세요.
# 1,000,000 / personas_per_second / 3600 = 예상 시간(시간 단위)
caffeinate -i .venv/bin/python engine/scripts/build_embeddings.py --batch-size 16 > "$PP_DATA_DIR/embedding-build.log" 2>&1
```

`--limit` 결과는 `multilingual-e5-large-v1-pilot-2000/`에 별도로 저장되며, 실제 검색에 사용되지 않습니다. 전체 생성은 읽기 전용 SQLite snapshot에서 스트리밍하고 임시 폴더에 저장합니다. 모두 끝나면 디렉터리를 한 번에 공개하므로 중단된 행렬이 검색에 쓰이지 않습니다. 기존 결과를 덮어쓰지 않으며, 다시 계산하려면 별도의 `PP_DATA_DIR`을 사용하세요. 실행 후 서버를 다시 시작하세요.

100만 명 float16 행렬은 약 2.05GB(1.91GiB)이며 UUID·모델 캐시·생성 중 임시 파일에 추가 공간이 필요합니다. 모델 다운로드를 제외하고도 맥미니 사양·열·batch 크기·텍스트 길이에 따라 시간이 크게 달라집니다. 맥북 MPS에서 원본 인물 128명만 생성한 시험(batch 8)은 약 11.3초(모델 로드 포함), 약 11.4명/초였습니다. 단순 외삽하면 약 24.4시간이며, 맥미니 실측값은 아닙니다. 2,000명 pilot으로 장비별 시간을 먼저 산정해야 합니다. 이 변경에서는 100만 명을 재계산하지 않았습니다.

모델 파일이 이미 캐시에 있으면 `HF_HUB_OFFLINE=1`로 허브 연결 없이 실행할 수 있습니다. 기본 모델 캐시는 `PP_DATA_DIR/hf`이며 `HF_HOME`이 설정돼 있으면 그 위치를 따릅니다.

## 기존 공개 예시의 계보

`web/public/runs/`의 예시 4건은 이전 검색 구성으로 영향권 인물을 고른 보관 결과입니다. 이번 변경에서 인물 선택이나 판단 결과를 재생성하지 않았습니다. 새 기본값 표시는 앞으로의 실행 설정이며, 예시가 새 임베딩으로 생성됐다는 뜻이 아닙니다. 검색 단계까지 새 모델만 쓴 예시가 필요하면 원본 정책에서 패널 선택 이후를 다시 실행해야 합니다. 판단 모델을 호출하는 재생성에는 별도 비용이 들 수 있습니다.
