# P8 latency: full hook call, JS vs Python

Command: `uv run python -m testkit.bench_gate --n 200` (calls interleaved; 7 mixed inputs cycled: Bash allow x2,
Bash ask x2, script scan, MCP allow, MCP ask; default packs; each call = `bash wrapper` + engine start).

Machine: Intel Core i7-9750H, macOS (Darwin 24.6.0), Node v25.9.0, Python 3.14.7, 2026-11-21.

| impl | wrapper | p50 | p95 |
| --- | --- | --- | --- |
| JS | `hooks/gate.sh` | 118.4 ms | 126.6 ms |
| Python | `testkit/_gate_py.sh` | 78.8 ms | 84.0 ms |

p95 Python - JS = -42.6 ms (budget: not more than +50 ms). A second run gave 117.0 / 127.1 (JS) and 78.6 / 83.7 ms (Python).
