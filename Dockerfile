FROM python:3.12-slim

# Node.js 20 для npx MCP-серверов (Gmail, Calendar, Slack, Confluence, Jira)
# uv для Python MCP-серверов (Telegram)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Зависимости Python
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Код и конфиг (credentials НЕ копируем — они из env vars)
COPY src/ src/
COPY config/ config/

# Директория для SQLite (монтируется как volume на Railway)
RUN mkdir -p data

ENV PYTHONUNBUFFERED=1

CMD ["python3.12", "-m", "src.main"]
