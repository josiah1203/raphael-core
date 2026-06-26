# raphael-core

API gateway — routing, auth middleware, rate limiting, compat shims

## API

- Prefix: `/v1`
- Port: `8080`
- Health: `GET /health`

## Events

_Published and consumed events documented in `openapi.yaml` and raphael-contracts._

## Development

```bash
uv sync
uv run uvicorn raphael_core.app:app --reload --port 8080
```

Part of the [Raphael Platform](https://github.com/hummingbird-labs) by HummingBird Labs.
