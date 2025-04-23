# syntax = docker/dockerfile:1.2
###################### Image with build tools to compile wheels ###############
FROM python:3.12-bookworm as wheels
ENV DEBIAN_FRONTEND=noninteractive

# Install only necessary build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libpq-dev \
    python3-dev \
    && python3 -m pip install -U pip \
    && rm -rf /var/lib/apt/lists/*

COPY constraints.txt requirements.txt /dallinger/
WORKDIR /dallinger

RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir /wheelhouse && \
    python3 -m pip wheel --wheel-dir=/wheelhouse -r requirements.txt -c constraints.txt

###################### Dallinger base image ###################################
FROM python:3.12-slim-bookworm as dallinger
ENV DEBIAN_FRONTEND=noninteractive \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    SKIP_DEPENDENCY_CHECK=true

LABEL org.opencontainers.image.source https://github.com/Dallinger/Dallinger
LABEL Description="Dallinger base docker image" Version="1.0"

EXPOSE 5000

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libpq5 \
    busybox \
    tzdata \
    pandoc \
    ca-certificates \
    curl \
    gnupg \
    && busybox --install \
    && python3 -m pip install -U pip \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI
RUN mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /dallinger
COPY constraints.txt requirements.txt ./
COPY . .

# Install Python dependencies using wheels from build stage
RUN --mount=type=bind,source=/wheelhouse,from=wheels,target=/wheelhouse \
    (ls -l /wheelhouse || (echo 'You need to enable docker buildkit to build dallinger: DOCKER_BUILDKIT=1' && false) ) && \
    python3 -m pip install --find-links file:///wheelhouse -r requirements.txt -c constraints.txt && \
    python3 -m pip install --find-links file:///wheelhouse -e .[data,docker]

CMD ["/bin/bash"]

###################### Dallinger bot image ####################################
FROM dallinger as dallinger-bot
ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/chromedownload \
    apt-get update && \
    apt-get install -y --no-install-recommends busybox jq && \
    rm -rf /var/lib/apt/lists/* && \
    CHROME_VERSION=$(curl https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json | jq .channels.Stable.version | tr -d '"') && \
    echo Installing Chrome $CHROME_VERSION && \
    CHROME_FILEPATH=/chromedownload/chrome-stable_${CHROME_VERSION}_linux64.zip && \
    ([ -f $CHROME_FILEPATH ] || busybox wget https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chrome-linux64.zip -O $CHROME_FILEPATH) && \
    busybox unzip $CHROME_FILEPATH -d /opt/ && \
    busybox ln -s /opt/chrome-linux64/chrome /usr/local/bin/chrome && \
    echo Installing ChromeDriver $CHROME_VERSION && \
    CHROMEDRIVER_FILEPATH=/chromedownload/chromedriver-stable_${CHROME_VERSION}_linux64.zip && \
    ([ -f $CHROMEDRIVER_FILEPATH ] || busybox wget https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chromedriver-linux64.zip -O $CHROMEDRIVER_FILEPATH) && \
    busybox unzip $CHROMEDRIVER_FILEPATH -d /usr/local/bin/
