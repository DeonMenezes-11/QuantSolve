"""QuantSolve: a self-verifying, self-healing solver for quantitative problems.

The package is split into small modules:

- ``config``   settings loaded from ``.env``
- ``llm``      thin OpenAI chat wrapper (JSON mode, retries, cost accounting)
- ``prompts``  every prompt the agent sends
- ``sandbox``  AST safety gate + restricted ``exec()`` in a child process
- ``faults``   deterministic bug injection used for demos and the benchmark
- ``agent``    the ReAct + Reflexion loop
- ``tasks``    sample problems with hand-written reference solutions
- ``benchmark`` / ``safety_eval``  evaluation scripts

This file is deliberately import-free: sandbox child processes import
``quantsolve.sandbox`` and should not pay for OpenAI or web-server imports.
"""

__version__ = "1.0.0"
