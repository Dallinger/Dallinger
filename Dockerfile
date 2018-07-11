FROM ubuntu:16.04
MAINTAINER Vishal Lall <lall@berkeley.edu>
LABEL Description="Docker for Dallinger" Version="1.1"
# Expose web server
EXPOSE 5000
# Install some dependencies
RUN apt-get update && apt-get install -y \
        build-essential \
        cmake \
        curl \
        enchant \
        g++ \
        gfortran \
        git \
        libffi-dev \
        libssl-dev \
        pandoc \
        python2.7 \
        python-dev \
        python-pip \
        redis-server \
        software-properties-common \
        supervisor \
        tox \
        unzip \
        vim \
        virtualenv \
        virtualenvwrapper \
        wget \
        default-jdk \
        zip \
        && \
    apt-get clean && \
    apt-get autoremove && \
    rm -rf /var/lib/apt/lists/*
# Install Dallinger
WORKDIR /home
RUN pip install --upgrade pip
RUN pip install pyenchant

RUN mkdir Dallinger
COPY . /home/Dallinger

# Heroku
RUN wget -qO- https://cli-assets.heroku.com/install-ubuntu.sh | sh

# Install Dallinger
#RUN dallinger setup
WORKDIR /home/Dallinger
# dev-requirements break with `pip install coverage_pth`
RUN pip install -r requirements.txt
RUN python setup.py develop

RUN apt-get update && apt-get install -y firefox

# Grab supervisord script
CMD /usr/bin/firefox
RUN echo "Docker-Dallinger is running... attach to container by running: docker run -p 5000:5000 -p 5432:5432 -p 6379:6379 --name dallinger-test1 <YOUR_IMAGE_NAME>"
