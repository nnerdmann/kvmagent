FROM harbor.nice.nokia.net/docker/python:3.11-bookworm

COPY . /app

COPY nice-root-ca.crt /usr/local/share/ca-certificates/nice-root-ca.crt
COPY nokia-root-ca.crt /usr/local/share/ca-certificates/nokia-root-ca.crt
RUN update-ca-certificates

ENV http_proxy=http://defraprx-fihelprx.glb.nsn-net.net:8080
ENV https_proxy=http://defraprx-fihelprx.glb.nsn-net.net:8080

# RUN apt-get update && \
#     apt-get install -y --no-install-recommends \
#     dmidecode \
#     lshw \
#     ssacli \
#     storcli \
#     ethtool \
#     ipmitool && \
#     rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir /app

ENV http_proxy=""
ENV https_proxy=""


WORKDIR /app
ENTRYPOINT ["python3","main.py"]
