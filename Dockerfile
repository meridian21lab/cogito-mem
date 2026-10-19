# syntax=docker/dockerfile:1.7
#
# cogito-mem in one container: the memory service, llama.cpp's llama-server, and
# (with BAKE_MODEL=1) the EmbeddingGemma 2 model.
#
#   docker build -t cogito-mem .
#   docker run -d --name cogito-mem -p 127.0.0.1:7327:7327 -v cogito-mem:/data cogito-mem
#   claude mcp add --transport http cogito-mem http://127.0.0.1:7327/mcp
#
# Without BAKE_MODEL the model (310 MB) is downloaded into the /data volume on first start.
# Behind a TLS-inspecting proxy, pass its CA for the build only (it is not kept in the image):
#   docker build --secret id=extra_ca,src=/path/to/proxy-ca.pem ...

# Debian 13: its GCC 14 compiles llama.cpp's newest ARM variants (armv9.2 with SME); GCC 12 cannot.
ARG PYTHON_IMAGE=python:3.12-slim-trixie

# ---------------------------------------------------------------- llama.cpp
FROM ${PYTHON_IMAGE} AS llama
ARG LLAMA_CPP_REF=ff5a23376725e5a889fa0bfb987b7541dc304da0
WORKDIR /src
# Portable CPU build: every x86/ARM variant is compiled and the best one is picked at run time.
RUN --mount=type=secret,id=extra_ca,required=false \
    cat /etc/ssl/certs/ca-certificates.crt /run/secrets/extra_ca > /tmp/ca.pem 2>/dev/null \
      || cp /etc/ssl/certs/ca-certificates.crt /tmp/ca.pem \
 && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
 && apt-get -o Acquire::https::CaInfo=/tmp/ca.pem update -qq \
 && apt-get -o Acquire::https::CaInfo=/tmp/ca.pem install -y -qq --no-install-recommends build-essential cmake git \
 && rm -rf /var/lib/apt/lists/* \
 && git init -q llama.cpp && cd llama.cpp \
 && git remote add origin https://github.com/ggml-org/llama.cpp \
 && GIT_SSL_CAINFO=/tmp/ca.pem git fetch -q --depth 1 origin "${LLAMA_CPP_REF}" && git checkout -q FETCH_HEAD \
 && cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF -DLLAMA_OPENSSL=OFF \
          -DGGML_NATIVE=OFF -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON \
          -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
 && cmake --build build --target llama-server -j"$(nproc)" \
 && mkdir -p /opt/llama && cp -P build/bin/llama-server build/bin/*.so* /opt/llama/ \
 && rm -f /tmp/ca.pem

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE}
ARG BAKE_MODEL=0
LABEL org.opencontainers.image.title="cogito-mem" \
      org.opencontainers.image.description="A fast, simple, local memory for agents (append/query, MCP)" \
      org.opencontainers.image.source="https://github.com/meridian21lab/cogito-mem" \
      org.opencontainers.image.licenses="MIT"
COPY --from=llama /opt/llama /opt/llama
COPY pyproject.toml README.md LICENSE /src/
COPY src /src/src
RUN --mount=type=secret,id=extra_ca,required=false \
    cat /etc/ssl/certs/ca-certificates.crt /run/secrets/extra_ca > /tmp/ca.pem 2>/dev/null \
      || cp /etc/ssl/certs/ca-certificates.crt /tmp/ca.pem \
 && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
 && apt-get -o Acquire::https::CaInfo=/tmp/ca.pem update -qq \
 && apt-get -o Acquire::https::CaInfo=/tmp/ca.pem install -y -qq --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && PIP_CERT=/tmp/ca.pem pip install --no-cache-dir --root-user-action=ignore /src && rm -rf /src \
 && if [ "${BAKE_MODEL}" = "1" ]; then \
      SSL_CERT_FILE=/tmp/ca.pem COGITO_MEM_HOME=/opt/cogito-mem cogito-mem setup --model-only \
      && echo "COGITO_MEM_MODEL=/opt/cogito-mem/models/embeddinggemma-2-Q8_0.gguf" > /etc/cogito-mem.env; \
    else : > /etc/cogito-mem.env; fi \
 && rm -f /tmp/ca.pem
ENV COGITO_MEM_HOME=/data \
    COGITO_MEM_LLAMA_SERVER=/opt/llama/llama-server \
    LD_LIBRARY_PATH=/opt/llama \
    COGITO_MEM_ALLOWED_HOSTS=host.docker.internal,cogito-mem \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 7327
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7327/v1/status', timeout=4)"
# /etc/cogito-mem.env points at a baked model, when there is one
ENTRYPOINT ["sh", "-c", "set -a; . /etc/cogito-mem.env; set +a; exec cogito-mem serve --host 0.0.0.0 --port 7327 --idle-timeout 0 \"$@\"", "--"]
