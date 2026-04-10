.PHONY: up down restart logs update build shell

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart bot

logs:
	docker compose logs -f

build:
	docker compose build --no-cache

update:
	git pull
	docker compose build --no-cache
	docker compose up -d
	docker compose logs -f --tail=50

shell:
	docker compose exec bot bash
