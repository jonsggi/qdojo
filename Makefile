.PHONY: test lint sync hooks cpp-test contract-test qubic-verify qubic-core-test qubic-core-syntax
test:
	uv run pytest -q packages/qdojo/tests
	node --test "apps/web/tests/*.test.cjs"
	@if command -v g++ >/dev/null 2>&1; then $(MAKE) --no-print-directory cpp-test; else echo "g++ not found; skipping cpp-test"; fi
	@if command -v g++ >/dev/null 2>&1; then $(MAKE) --no-print-directory contract-test; else echo "g++ not found; skipping contract-test"; fi
cpp-test:
	printf '#include "combat_core.h"\n#include "sha256.h"\n' | g++ -std=c++17 -x c++ -fsyntax-only -Wall -Wextra -Werror -Wconversion -fno-exceptions -fno-rtti -nostdinc++ -Icontracts/combat_core -
	g++ -std=c++17 -O2 -Wall -Wextra -Werror -o contracts/combat_core/test_combat_core contracts/combat_core/test_combat_core.cpp
	contracts/combat_core/test_combat_core .
contract-test:
	printf '#include "combat_contract.h"\n' | g++ -std=c++17 -x c++ -fsyntax-only -Wall -Wextra -Werror -Wconversion -fno-exceptions -fno-rtti -nostdinc++ -Icontracts/combat_contract -
	g++ -std=c++17 -O2 -Wall -Wextra -Werror -o contracts/combat_contract/test_contract contracts/combat_contract/test_contract.cpp
	contracts/combat_contract/test_contract packages/qdojo/tests/combat/fixtures/contract/*.journal
# Qubic Core tooling for contracts/qubic/QDOJO.h (clones and builds in QDOJO_QUBIC_WORK, default /tmp/qdojo-qubic; -j1).
qubic-verify:
	python3 contracts/qubic/core_harness.py verify
qubic-core-test:
	python3 contracts/qubic/core_harness.py test
qubic-core-syntax:
	python3 contracts/qubic/core_harness.py core-syntax
lint:
	uv run python -m compileall -q packages/qdojo/src
sync:
	uv sync
hooks:
	git config core.hooksPath .githooks && chmod +x .githooks/pre-commit
