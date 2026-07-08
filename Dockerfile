FROM python:3.11-slim

WORKDIR /app

# 의존성 레이어 분리 (코드 변경 시 재설치 방지)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY src/ src/
COPY config/ config/
RUN pip install --no-cache-dir -e .

# data/(SQLite), logs/ 는 볼륨으로 마운트 (docker-compose.yml 참고)
# .env 도 볼륨으로 주입 — 이미지에 비밀키를 굽지 않는다
CMD ["python", "-m", "quant.cli", "paper"]
