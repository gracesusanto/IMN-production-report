# IMN Production Report

This is the backend for IMN Production Report

## Local Setup

Docker is used to run the backend server and database. To run the backend endpoints, 
you will need to install Docker and docker-compose.

To install docker: https://docs.docker.com/get-docker/

To install docker-compose: https://docs.docker.com/compose/install/ - you may
not have to install depending on if you have MacOS, windows, etc as detailed in
the website

Then, you need to write an .env file. The backend code comes 
with a sample .env file you can use to bootstrap your own file.
You will need to copy this file and configure it with your application's
settings for this wo work. You can either do this manually, by copying 
and pasting the contents of `.env.template` into your own file and saving 
that as `.env`, or you can run: 
```sh
$ cp .env.example .env
```

You can start building the container by running this command:
```sh
$ docker-compose build
```

Once the container has been built, you can bring the container up
with the following command:
```sh
$ docker-compose up
```

Make sure that these have run successfully. A good way to confirm 
that things are working is to take a look at the API docs at http://localhost:8000/docs/
Note that for `dev`, the postgres database schemas *has been automatically migrated* by
the `alembic upgrade head` command run when spinning up the docker container. 
All you have to do next is to populate the database.

The backend code comes with a sample `data_all_for_test.csv` file you can use to fill 
the database, as well as a python script `db_ingestion.py` that reads the entries in 
`data_all.csv` and input the values into the database. So you need to first copy the entries from 
`data_all_for_test.csv` into `data_all.csv`, and then run the `db_ingestion.py` script. 
You can run the following commands to populate the database:
```sh
$ cp data_all_for_test.csv data_all.csv
$ docker-compose exec app python3 db_ingestion.py
```

## Integration with IMN Productio QR Code Scanner App

The frontend code accepts QR code of id as input. To generate QR codes you 
can use to do end-to-end testing, you need to generate QR codes based on the ids
stored in the database. You can run the following to get the ids from database:
```sh
$ docker-compose exec app python3 get_id.py
```

The resulting ids will be stored in `data/IDs/{category}_ids.csv` for each category in [tooling, mesin, operator]. Then, you can generate the QR codes using third party QR code generator.

Alternatively, you can ask our admin to provide you with a spreadsheet that generates the QR codes.
