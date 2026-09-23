# SPZ AI Image Generation Proxy

A1111 WebUI API -> GPT Image 2.5 API protocol converter for Stable Projectorz.

## Modes

### mock (offline protocol test)

No API key needed. Returns test images for protocol validation.

```bash
python proxy/fake_a1111_server.py
```

Listens on `127.0.0.1:7860`. Returns preset responses for all SPZ-required endpoints.

### live (real API generation)

Requires `OPENAI_API_KEY`. Converts A1111 protocol requests to GPT Image 2.5 API calls.

```bash
export OPENAI_API_KEY=sk-...
python proxy/gpt_image_proxy.py
```

Without `OPENAI_API_KEY`, the proxy will **refuse to generate** and return an explicit error (no test images in live mode).

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (none) | Required for live mode |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API base URL |
| `SPZ_PROXY_PORT` | `7860` | Listen port |
| `SPZ_PROXY_HOST` | `127.0.0.1` | Listen address |
| `SPZ_DEFAULT_MODEL` | `gpt-image-2.5-sunburst` | Default model |

## Dependencies

```
fastapi>=0.100
uvicorn>=0.20
Pillow>=9.0
httpx>=0.24
```

Install: `pip install -r proxy/requirements.txt`

## Endpoints

All A1111-compatible endpoints that SPZ expects:

- `GET /internal/ping` - connection check
- `GET /sdapi/v1/options` - current model
- `POST /sdapi/v1/options` - set model
- `GET /sdapi/v1/sd-models` - model list
- `GET /sdapi/v1/samplers` - sampler list
- `GET /sdapi/v1/sd-schedulers` - scheduler list
- `GET /sdapi/v1/schedulers` - scheduler list (alt)
- `GET /sdapi/v1/upscalers` - upscaler list
- `POST /sdapi/v1/txt2img` - text to image
- `POST /sdapi/v1/img2img` - image to image (with mask)
- `POST /sdapi/v1/interrupt` - cancel generation
- `POST /sdapi/v1/controlnet/detect` - ControlNet passthrough
- `GET /sdapi/v1/progress` - progress query

## SPZ Connection

1. Start proxy (mock or live)
2. In SPZ: Settings -> Connection -> Server URL: `http://127.0.0.1:7860`
3. Click "Connect" - should see green connection indicator

## Known Limitations

- GPT Image 2.5 does not support: sampler selection, CFG scale, step count, scheduler
- These parameters are accepted by the proxy but do not affect generation
- SPZ UI may show them as available; they should be marked as "not supported" in a future update
- Model switching takes effect on the next request
