# PyForge Playground

A local interactive dashboard for exercising the real PyForge package. It is a repository tool and is not included in the published wheel.

## Run on Windows PowerShell

From the repository root:

```powershell
python -m pip install --upgrade pip "setuptools>=77" wheel
python -m pip install -e .
python -m playground.server
```

Open **http://127.0.0.1:8765** in your browser. Stop the server with `Ctrl+C`.

The playground uses only the Python standard library in addition to PyForge itself. The server binds to `127.0.0.1` port `8765`. It runs only the fixed `DEMOS` mapping. It does not accept arbitrary Python, and it does not send external HTTP requests. Request bodies must be JSON of 1 to 10,000 bytes. There is no authentication. This server is for local development only and is not a public deployment. If a demonstration raises, the error response includes the exception text for the local browser.

## Included demonstrations

- Retry engine and retry observer lifecycle
- Structured JSON logging and documented redaction
- Typed environment configuration
- HTTP retry eligibility decisions
- Memory cache TTL and LRU behavior
- Deterministic testing helpers

Each Run action calls the installed PyForge package. The examples use deterministic inputs and avoid real sleep delays.
