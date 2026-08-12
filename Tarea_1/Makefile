# Makefile

.PHONY: up down seed restart

# Levanta todos los servicios en segundo plano y los reconstruye si hay cambios
up:
	docker compose up --build -d

# Apaga todos los contenedores y elimina la red
down:
	docker compose down

# Ejecuta el script para poblar las bases de datos
seed:
	cd service_01 && bash seed.sh

# Reinicia todo desde cero
restart: down up