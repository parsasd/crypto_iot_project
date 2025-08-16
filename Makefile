PROJECT_NAME=crypto_iot
COMPOSE=docker compose --project-name $(PROJECT_NAME) -f infra/docker-compose.yml

.PHONY: up down seed demo logs test

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f

# Seed the database with demo data
seed:
	$(COMPOSE) exec alert_engine python seed.py

# Launch the professor demo: start services, seed data and open the webapp
demo: up seed
	@echo "Demo services started. Navigate to http://localhost:3000 and login with demo@example.com. Check MailHog at http://localhost:8025 for the OTP."

test:
	pytest -q