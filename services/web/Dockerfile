FROM python:3.10-slim-bullseye
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

RUN apt-get update && \
    apt-get -y install python3-pandas libpq-dev build-essential postgresql-client cron bash && \
    rm -rf /var/lib/apt/lists/*

# Install the repository and then install the PostgreSQL 16 client
RUN apt-get update && \
    apt-get install -y wget gnupg dirmngr --no-install-recommends && \
    echo "deb http://apt.postgresql.org/pub/repos/apt/ bullseye-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
    wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - && \
    apt-get update && \
    apt-get install -y postgresql-client-16 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY ./requirements.txt requirements.txt
RUN pip3 install --upgrade pip
RUN pip3 install --no-cache-dir --upgrade -r requirements.txt
COPY ./ /app
COPY ./backup/backup.sh /app
COPY ./backup/crontab /etc/cron.d/backup-cron
RUN chmod +x ./backup/backup.sh
RUN chmod 0644 /etc/cron.d/backup-cron && crontab /etc/cron.d/backup-cron

COPY start.sh /start.sh
RUN chmod +x /start.sh
CMD ["/start.sh"]
