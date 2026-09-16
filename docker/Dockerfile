FROM python:3.11-slim

# 定义可替换的镜像源参数，默认使用阿里云
ARG DEBIAN_MIRROR=mirrors.aliyun.com


# 把阿里云换掉，换成清华源（或者中科大源：mirrors.ustc.edu.cn）
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources

# 2. 执行安装
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ripgrep curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace