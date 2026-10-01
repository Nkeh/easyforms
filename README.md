# easyforms

Hosted form backend with ML spam filtering. 

## Local setup

```
cp .env.example .env
make up             # docker compose up --build (first run also builds the image)
make migrate         # in a second terminal, once db is healthy
make test
make lint
```

Visit `http://localhost:8000/healthz`. Create an admin user with:

```
docker compose run --rm web python manage.py createsuperuser
```

Then log in at `http://localhost:8000/admin/`.
