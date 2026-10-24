FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/Hafsa-Anwar65/envsure"
LABEL org.opencontainers.image.description="Validate .env files, keep .env.example in sync, and catch leaked API keys."
LABEL org.opencontainers.image.licenses="MIT"
WORKDIR /pkg
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf /pkg
WORKDIR /work
ENTRYPOINT ["envsure"]
CMD ["--help"]
