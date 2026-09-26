.PHONY: install dev test test-backend test-frontend api worker build backup smoke

install:
	python3 -m venv .venv
	.venv/bin/pip install -r backend/requirements.txt
	cd frontend && npm install

# The one command for local development: API + Vite together, demo database,
# console email. Ctrl-C stops both. See scripts/dev.sh for why a static server
# (VS Code Live Server) cannot serve this project.
dev:
	./scripts/dev.sh

test: test-backend test-frontend

test-backend:
	.venv/bin/python -m pytest backend/tests

test-frontend:
	cd frontend && npm test

# The API alone. `make dev` is usually what you want instead - it also starts
# the UI. Note -u: the console email backend prints verification codes to
# stdout, and Python buffers that away when it is redirected.
api:
	.venv/bin/python -u backend/wsgi.py

worker:
	cd backend && ../.venv/bin/python run_worker.py

build:
	cd frontend && npm run build

backup:
	.venv/bin/python backend/backup_db.py

# Real HTTP validation. Start `make api` in another shell first.
smoke:
	./scripts/smoke_test.sh
