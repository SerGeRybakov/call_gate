docker compose down
docker compose up -d
pytest --cov=./call_gate --cov-report=html --cov-report=term-missing --cov-branch
echo 'Find html report at ./tests/code_coverage/index.html'
