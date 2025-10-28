setup:
	RESET_DB=true docker compose up --build

build:
	RESET_DB='' docker compose build

db:
	RESET_DB=true docker compose run --remove-orphans holvi-api python db_setup.py

up:
	RESET_DB='' docker compose up --remove-orphans

down:
	RESET_DB='' docker compose down

attempts ?= 10
concurrency ?= 2
sleep_between_payouts ?= 0.02
call:
	RESET_DB='' docker compose exec -e CONCURRENCY=$(concurrency) -e GENERATION_ATTEMPTS=$(attempts) -e SLEEP_BETWEEN_PAYOUT=$(sleep_between_payouts) expenzy-server python producer.py

load:
	RESET_DB='' time docker compose exec -e CONCURRENCY=100 -e GENERATION_ATTEMPTS=10000 -e SLEEP_BETWEEN_PAYOUT=0.02 expenzy-server python producer.py

report:
	RESET_DB='' docker compose exec holvi-api python db_check.py