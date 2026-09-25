.PHONY: up down test lint fmt migrate makemigrations shell

up:
	docker compose up --build

down:
	docker compose down

test:
	docker compose run --rm web pytest

lint:
	docker compose run --rm web sh -c "ruff check . && ruff format --check ."

fmt:
	docker compose run --rm web ruff format .

migrate:
	docker compose run --rm web python manage.py migrate

makemigrations:
	docker compose run --rm web python manage.py makemigrations

shell:
	docker compose run --rm web python manage.py shell
