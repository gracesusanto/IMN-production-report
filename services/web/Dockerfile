FROM python:3.10-slim-bullseye
ENV PYTHONUNBUFFERED=1
RUN apt-get update && \
    apt-get -y install python3-pandas \
    libpq-dev build-essential postgresql-client

ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY ./requirements.txt requirements.txt
RUN pip3 install --upgrade pip
RUN pip3 install --no-cache-dir --upgrade -r requirements.txt
COPY ./ /app
EXPOSE 8000