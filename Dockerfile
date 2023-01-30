FROM python:3
ENV PYTHONUNBUFFERED=1
RUN apt-get update && \
    apt-get -y install python3-pandas \
    libpq-dev build-essential postgresql-client

# RUN apk update && apk add postgresql-dev gcc python3-dev musl-dev
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements.txt
RUN pip3 install --upgrade pip
RUN pip3 install --no-cache-dir --upgrade -r requirements.txt
COPY . /app
EXPOSE 8000