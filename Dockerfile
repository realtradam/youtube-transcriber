FROM python:3.12-alpine3.21 AS builder

WORKDIR /app

RUN python -m venv --copies /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
RUN pip install --no-cache-dir $(python -c "import tomllib; print(' '.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))")

FROM python:3.12-alpine3.21

RUN apk add --no-cache wget

RUN addgroup -g 1001 -S appgroup && adduser -u 1001 -S appuser -G appgroup

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY app/ ./app/

RUN mkdir -p /app/data && chown appuser:appgroup /app/data

USER appuser

EXPOSE 41090

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://localhost:41090/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "41090"]
