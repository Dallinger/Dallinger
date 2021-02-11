# syntax = docker/dockerfile:1.2
FROM ubuntu:20.04 as wheels
ENV DEBIAN_FRONTEND=noninteractive

LABEL Description="Dallinger base docker image" Version="1.0"

EXPOSE 5000

# Install build dependencies
RUN apt-get update && \
    apt-get install -y libpq-dev python3-pip python3-dev enchant tzdata pandoc && \
    rm -rf /var/lib/apt/lists/*

COPY . /dallinger
WORKDIR /dallinger

RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir /wheelhouse && \
    python3 -m pip wheel --wheel-dir=/wheelhouse -r requirements.txt .

FROM ubuntu:20.04
ENV DEBIAN_FRONTEND=noninteractive

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y libpq5 python3-pip enchant tzdata && \
    rm -rf /var/lib/apt/lists/*

COPY . /dallinger
WORKDIR /dallinger

RUN --mount=type=bind,source=/wheelhouse,from=wheels,target=/wheelhouse \
    python3 -m pip install --find-links /wheelhouse -r requirements.txt && \
    python3 -m pip install --find-links /wheelhouse -e .[data]

# Add two ENV variables as a fix when using python3, to prevent this error:
# Click will abort further execution because Python 3 was configured
# to use ASCII as encoding for the environment.
# Consult http://click.pocoo.org/python3/for mitigation steps.
ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8

CMD /bin/bash