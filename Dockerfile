FROM registry.access.redhat.com/ubi9/python-311:latest

ARG VCS_REF=unknown

LABEL maintainer="vcore" \
      description="vCore provides a vCenter-compatible API powered by RVtools XLSX exports" \
      org.opencontainers.image.source="https://github.com/alfbach/vCore" \
      org.opencontainers.image.revision="${VCS_REF}" \
      io.k8s.display-name="vCore" \
      io.openshift.tags="python,fastapi,vcenter,emulator"

USER 0

WORKDIR /opt/app

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    mkdir -p /var/lib/vcenteremu/uploads && \
    chgrp -R 0 /var/lib/vcenteremu /opt/app && \
    chmod -R g+rwX /var/lib/vcenteremu /opt/app

ENV VCENTEREMU_HOST=0.0.0.0 \
    VCENTEREMU_PORT=8181 \
    VCENTEREMU_UPLOAD_DIR=/var/lib/vcenteremu/uploads \
    VCENTEREMU_WORKERS=1 \
    VCENTEREMU_API_USERNAME=admin \
    VCENTEREMU_API_PASSWORD=changeme \
    VCENTEREMU_ALLOW_WEAK_PASSWORD=true \
    PYTHONUNBUFFERED=1

EXPOSE 8181

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8181/health', timeout=3)" || exit 1

USER 1001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8181"]
