FROM certbot/certbot:latest
RUN apk upgrade --no-cache \
    && uv pip install --system --upgrade msgpack setuptools urllib3 \
    && uv pip check --system \
    && uv pip uninstall --system pip setuptools wheel \
    && uv cache clean
