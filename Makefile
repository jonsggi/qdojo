.PHONY: test lint sync hooks
test:
	uv run pytest -q packages/qdojo/tests
	node --test "apps/web/tests/*.test.cjs"
lint:
	uv run python -m compileall -q packages/qdojo/src
sync:
	uv sync
hooks:
	git config core.hooksPath .githooks && chmod +x .githooks/pre-commit
