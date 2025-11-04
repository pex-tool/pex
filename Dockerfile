FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        python3-venv \
        curl \
        openssh-client \
        zip unzip \
        patch \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir -r requirements.txt

CMD ["python", "-m", "pytest", "-v"]
