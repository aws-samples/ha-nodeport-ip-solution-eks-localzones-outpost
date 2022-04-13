# syntax=docker/dockerfile:1
FROM public.ecr.aws/amazonlinux/amazonlinux:latest
WORKDIR /app
RUN yum -y install python3
RUN yum -y install iproute
RUN yum -y install iputils
COPY requirements.txt requirements.txt
COPY script.sh script.sh
COPY assign-secondary-ip.py assign-secondary-ip.py
RUN pip3 install  -r requirements.txt
RUN chmod 755 /app/script.sh
