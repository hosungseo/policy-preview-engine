# 백번 미리 묻다 · 현장 질문 미리 설계(시범) — one container: static web + API + run executor.
# Answers come from TypeSafe Jev (TYPESAFE_API_KEY), or from a compatible local decision-model server
# (PP_JEV_URL). Build the panel bundle first (engine/scripts/build_panel_from_nemotron.py); it is copied into the image
# with engine/ppservice/data.
# Data lives in /data (mount a volume).
#
# The deep analysis after a survey (ppservice.deep) writes with a language model reached over an
# OpenAI-compatible API: -e PP_LLM_PROVIDER=openai -e PP_LLM_BASE_URL=... -e PP_LLM_MODEL=...
# [-e PP_LLM_API_KEY=...]. Without those it runs with PP_LLM_PROVIDER=mock (placeholder text, labelled).
#
#   docker build -t policy-review .
#   docker run -p 8800:8800 -v policy-review-data:/data \
#     -e PP_JEV_PROVIDER=api -e TYPESAFE_API_KEY=... -e PP_COOKIE_SECURE=1 policy-review
#   docker exec -it <container> python -m ppservice user add officer@example.go.kr

FROM node:24-slim AS web
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PP_SERVICE_DATA=/data PP_DATA_DIR=/data/engine PP_WEB_OUT=/app/web/out PP_JEV_PROVIDER=api \
    PP_LLM_PROVIDER=mock
WORKDIR /app/engine
COPY engine/requirements-service.txt ./
RUN pip install --no-cache-dir -r requirements-service.txt
COPY engine/pp ./pp
COPY engine/ppservice ./ppservice
COPY --from=web /app/web/out /app/web/out
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app /data
USER app
VOLUME /data
EXPOSE 8800
CMD ["python", "-m", "ppservice", "serve", "--host", "0.0.0.0", "--port", "8800"]
