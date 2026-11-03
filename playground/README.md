# PyForge Playground

A local interactive dashboard for exercising the real PyForge package. It is a repository tool and is not included in the published wheel.

## Run on Windows PowerShell

From the repository root:

```powershell
python -m pip install -e .
python -m playground.server
```

Open **http://127.0.0.1:8765** in your browser. Stop the server with `Ctrl+C`.

The playground uses only the Python standard library in addition to PyForge itself. It binds to loopback only and exposes a fixed set of demonstration actions. It does not accept arbitrary Python code or send external HTTP requests.

## Included demonstrations

- Retry engine and retry observer lifecycle
- Structured JSON logging and documented redaction
- Typed environment configuration
- HTTP retry eligibility decisions
- Memory cache TTL and LRU behavior
- Deterministic testing helpers

Each Run action calls the installed PyForge package. The examples use deterministic inputs and avoid real sleep delays.
