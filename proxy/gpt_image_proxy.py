"""
GPT Image 2.5 API Proxy v0.5.0
==============================
A1111 WebUI API -> OpenAI Image API protocol converter.
Provides AI image generation backend for Stable Projectorz (SPZ).

v0.5.0 fixes:
  - Added POST /sdapi/v1/controlnet/detect (module=none passthrough)
  - Fixed /progress state to match SD_GenProgressResponseState spec
  - No-key mode: txt2img/img2img return test images instead of 500 error
  - Fixed /interrupt response to return {cancelled: true} per spec

v0.4.0 fixes:
  - Added GET /internal/ping (SPZ connection check)
  - Added GET /sdapi/v1/sd-models (model list)
  - Added POST /sdapi/v1/options (set model)
  - Added POST /sdapi/v1/interrupt (cancel)
  - Added GET /sdapi/v1/upscalers (alt path)
  - Added response_format=b64_json to OpenAI calls

Endpoints:
  GET  /internal/ping         - SPZ connection check
  GET  /sdapi/v1/options      - model options
  POST /sdapi/v1/options      - set model
  GET  /sdapi/v1/sd-models    - model list
  GET  /sdapi/v1/samplers     - sampler list
  GET  /sdapi/v1/sd-schedulers- scheduler list
  GET  /sdapi/v1/schedulers   - scheduler list (alt)
  GET  /sdapi/v1/upscalers    - upscaler list
  GET  /sdapi/v1/upscale-models - upscaler list (alt)
  POST /sdapi/v1/txt2img      - text to image
  POST /sdapi/v1/img2img      - image to image (with mask)
  POST /sdapi/v1/interrupt    - cancel generation
  POST /sdapi/v1/controlnet/detect - ControlNet preprocess (passthrough)
  GET  /sdapi/v1/progress     - progress query
  GET  /                      - homepage

Env vars:
  OPENAI_API_KEY   - OpenAI API key (required for real generation)
  OPENAI_BASE_URL  - API base URL (optional, default https://api.openai.com/v1)
  SPZ_PROXY_PORT   - listen port (optional, default 7860)
  SPZ_PROXY_HOST   - listen address (optional, default 127.0.0.1)
  SPZ_DEFAULT_MODEL - default model (optional, default gpt-image-2.5-sunburst)
"""
import os
import sys
import time
import json
import base64
import logging
from io import BytesIO
from typing import Optional

try:
    import httpx
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import JSONResponse, HTMLResponse, Response
    import uvicorn
    from PIL import Image
except ImportError as e:
    print("Missing dependency: " + str(e))
    print("Install with: pip install httpx fastapi uvicorn Pillow")
    sys.exit(1)

API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
PORT = int(os.environ.get("SPZ_PROXY_PORT", "7860"))
HOST = os.environ.get("SPZ_PROXY_HOST", "127.0.0.1")
DEFAULT_MODEL = os.environ.get("SPZ_DEFAULT_MODEL", "gpt-image-2.5-sunburst")

if not API_KEY:
    print("WARNING: OPENAI_API_KEY not set! Proxy will start in no-key mode.")
    print("  txt2img/img2img will return test images for protocol validation.")
    print("  Set it with: $env:OPENAI_API_KEY = 'sk-...'")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("spz-proxy")

app = FastAPI(title="SPZ GPT Image Proxy", version="0.5.0")

SAMPLERS = [
    {"name": "Euler", "aliases": ["euler"], "options": {}},
    {"name": "Euler a", "aliases": ["euler_a"], "options": {}},
    {"name": "DPM++ 2M", "aliases": ["dpmpp_2m"], "options": {}},
    {"name": "DPM++ 2M Karras", "aliases": ["dpmpp_2m_karras"], "options": {}},
    {"name": "DDIM", "aliases": ["ddim"], "options": {}},
]

SCHEDULERS = [
    {"name": "Automatic", "aliases": ["automatic"]},
    {"name": "Karras", "aliases": ["karras"]},
    {"name": "Exponential", "aliases": ["exponential"]},
    {"name": "Simple", "aliases": ["simple"]},
]

UPSCALE_MODELS = [
    {"name": "None", "model_name": "None"},
    {"name": "R-ESRGAN 4x", "model_name": "R-ESRGAN 4x"},
    {"name": "R-ESRGAN 4x+", "model_name": "R-ESRGAN 4x+"},
]

AVAILABLE_MODELS = [
    {"title": DEFAULT_MODEL, "model_name": DEFAULT_MODEL, "hash": "gpt25", "sha256": "gpt25", "filename": DEFAULT_MODEL + ".safetensors"},
]

CURRENT_OPTIONS = {
    "sd_model_checkpoint": DEFAULT_MODEL,
    "sd_vae": "Automatic",
    "CLIP_stop_at_last_layers": 1,
    "sd_checkpoint_hash": "gpt-image-2.5",
}

# Task state for progress tracking (spec: SD_GenProgressResponseState)
TASK_STATE = {
    "job": "",
    "job_count": 0,
    "sampling_step": 0,
    "sampling_steps": 0,
}
TASK_TEXTINFO = "Idle"


def make_test_image(w=512, h=512, color=(100, 150, 200)):
    """Generate a solid-color test image as base64 data URI."""
    img = Image.new("RGB", (w, h), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def b64_encode_image(img, format="PNG"):
    buf = BytesIO()
    img.save(buf, format=format)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def b64_decode_image(b64_str):
    if "," in b64_str:
        b64_str = b64_str.split(",", 1)[1]
    return Image.open(BytesIO(base64.b64decode(b64_str)))


def map_size_to_openai(width, height):
    if width == height:
        return "1024x1024"
    elif width > height:
        return "1536x1024"
    else:
        return "1024x1536"


def no_key_response(prompt, width, height, seed, is_img2img=False):
    """Return a test image when API key is not set."""
    log.info("  [no-key mode] returning test image")
    actual_seed = seed if seed >= 0 else int(time.time()) % 2**32
    color = (200, 100, 100) if is_img2img else (100, 150, 200)
    return {
        "images": [make_test_image(width, height, color)],
        "parameters": {
            "prompt": prompt,
            "steps": 20,
            "width": width,
            "height": height,
            "seed": actual_seed,
        },
        "info": json.dumps({
            "infotexts": ["[NO-KEY MODE] test image, prompt=" + prompt[:40] + ", seed=" + str(actual_seed)],
            "seed": actual_seed,
        }),
    }


async def call_openai_image(
    prompt, negative_prompt="", width=1024, height=1024,
    steps=20, cfg_scale=7.0, seed=-1,
    init_image=None, mask_image=None,
    denoising_strength=0.75, sampler_name="euler", batch_size=1,
):
    if not API_KEY:
        return no_key_response(prompt, width, height, seed, is_img2img=(init_image is not None))

    size = map_size_to_openai(width, height)

    payload = {
        "model": DEFAULT_MODEL,
        "prompt": prompt,
        "n": batch_size,
        "size": size,
        "response_format": "b64_json",
    }

    if negative_prompt:
        payload["prompt"] = prompt + "\n\nAvoid: " + negative_prompt

    headers = {
        "Authorization": "Bearer " + API_KEY,
        "Content-Type": "application/json",
    }

    url = BASE_URL + "/images/generations"
    if init_image is not None:
        url = BASE_URL + "/images/edits"

    log.info("Calling OpenAI: model=" + DEFAULT_MODEL + " size=" + size + " prompt=" + prompt[:60])
    start_time = time.time()

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            if init_image is not None:
                files = {}
                data = {
                    "model": DEFAULT_MODEL,
                    "prompt": payload["prompt"],
                    "n": str(batch_size),
                    "size": size,
                    "response_format": "b64_json",
                }

                img_buf = BytesIO()
                init_image.save(img_buf, format="PNG")
                img_buf.seek(0)
                files["image"] = ("image.png", img_buf, "image/png")

                if mask_image is not None:
                    mask_buf = BytesIO()
                    mask_image.convert("L").save(mask_buf, format="PNG")
                    mask_buf.seek(0)
                    files["mask"] = ("mask.png", mask_buf, "image/png")

                headers_mp = {"Authorization": "Bearer " + API_KEY}
                resp = await client.post(url, headers=headers_mp, files=files, data=data, timeout=300.0)
            else:
                resp = await client.post(url, headers=headers, json=payload, timeout=300.0)

            elapsed = time.time() - start_time
            log.info("OpenAI responded in " + str(round(elapsed, 1)) + "s status=" + str(resp.status_code))

            if resp.status_code != 200:
                error_detail = resp.text[:500]
                log.error("OpenAI error: " + error_detail)
                raise HTTPException(status_code=502, detail="OpenAI API error: " + error_detail)

            result = resp.json()

            images = []
            for item in result.get("data", []):
                if "b64_json" in item:
                    images.append("data:image/png;base64," + item["b64_json"])
                elif "url" in item:
                    img_resp = await client.get(item["url"])
                    b64 = base64.b64encode(img_resp.content).decode()
                    images.append("data:image/png;base64," + b64)

            actual_seed = seed if seed >= 0 else int(time.time()) % 2**32

            return {
                "images": images,
                "parameters": {
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "steps": steps,
                    "cfg_scale": cfg_scale,
                    "width": width,
                    "height": height,
                    "sampler_name": sampler_name,
                    "seed": actual_seed,
                    "denoising_strength": denoising_strength if init_image else None,
                },
                "info": json.dumps({
                    "infotexts": [prompt + " Steps: " + str(steps) + ", CFG: " + str(cfg_scale) + ", Seed: " + str(actual_seed) + ", Size: " + str(width) + "x" + str(height) + ", Model: " + DEFAULT_MODEL],
                    "seed": actual_seed,
                }),
            }

        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="OpenAI API timeout (300s)")
        except httpx.ConnectError as e:
            raise HTTPException(status_code=502, detail="Cannot connect to OpenAI: " + str(e))


@app.get("/internal/ping")
async def internal_ping():
    return Response(content="OK", media_type="text/plain")


@app.get("/ping")
async def ping():
    return Response(content="OK", media_type="text/plain")


@app.get("/")
async def root():
    return HTMLResponse("<html><body style='font-family: monospace; padding: 20px;'><h2>SPZ GPT Image Proxy v0.5.0</h2><p>Model: <b>" + DEFAULT_MODEL + "</b></p><p>API Key: " + ("SET" if API_KEY else "NOT SET (no-key mode)") + "</p></body></html>")


@app.get("/sdapi/v1/options")
async def get_options():
    return CURRENT_OPTIONS


@app.post("/sdapi/v1/options")
async def set_options(request: Request):
    body = await request.json()
    for k, v in body.items():
        if k in CURRENT_OPTIONS:
            CURRENT_OPTIONS[k] = v
    log.info("POST /options -> updated: " + str(list(body.keys())))
    return {"status": "ok"}


@app.get("/sdapi/v1/sd-models")
async def get_models():
    return AVAILABLE_MODELS


@app.get("/sdapi/v1/samplers")
async def get_samplers():
    return SAMPLERS


@app.get("/sdapi/v1/sd-schedulers")
async def get_sd_schedulers():
    return SCHEDULERS


@app.get("/sdapi/v1/schedulers")
async def get_schedulers():
    return SCHEDULERS


@app.get("/sdapi/v1/upscalers")
async def get_upscalers():
    return UPSCALE_MODELS


@app.get("/sdapi/v1/upscale-models")
async def get_upscale_models():
    return UPSCALE_MODELS


@app.get("/sdapi/v1/progress")
async def get_progress():
    return {
        "progress": 0.0,
        "eta_relative": 0.0,
        "state": TASK_STATE,
        "current_image": "",
        "textinfo": TASK_TEXTINFO,
    }


@app.post("/sdapi/v1/interrupt")
async def interrupt():
    global TASK_STATE, TASK_TEXTINFO
    TASK_STATE["job"] = "cancelled"
    TASK_TEXTINFO = "Cancelled"
    log.info("POST /interrupt -> task cancelled")
    return {"cancelled": True}


@app.post("/sdapi/v1/controlnet/detect")
async def controlnet_detect(request: Request):
    body = await request.json()
    module = body.get("module", "none")
    if module == "none" or module == "None":
        input_img = body.get("image", "")
        return {"images": [input_img] if input_img else []}
    else:
        return JSONResponse(
            status_code=400,
            content={"detail": "ControlNet module not supported. Proxy only supports module=none (passthrough)."}
        )


@app.post("/sdapi/v1/txt2img")
async def txt2img(request: Request):
    body = await request.json()
    log.info("txt2img: prompt=" + body.get("prompt", "")[:50] + " size=" + str(body.get("width", "?")) + "x" + str(body.get("height", "?")))
    return await call_openai_image(
        prompt=body.get("prompt", ""),
        negative_prompt=body.get("negative_prompt", ""),
        width=body.get("width", 1024),
        height=body.get("height", 1024),
        steps=body.get("steps", 20),
        cfg_scale=body.get("cfg_scale", 7.0),
        seed=body.get("seed", -1),
        sampler_name=body.get("sampler_name", "euler"),
        batch_size=body.get("batch_size", 1),
    )


@app.post("/sdapi/v1/img2img")
async def img2img(request: Request):
    body = await request.json()
    log.info("img2img: prompt=" + body.get("prompt", "")[:50] + " denoise=" + str(body.get("denoising_strength", 0.75)))

    init_image = None
    mask_image = None

    init_images = body.get("init_images", [])
    if init_images:
        init_image = b64_decode_image(init_images[0])
        log.info("  init_image: " + str(init_image.size))

    mask = body.get("mask", "")
    if mask:
        mask_image = b64_decode_image(mask)
        log.info("  mask: " + str(mask_image.size))

    return await call_openai_image(
        prompt=body.get("prompt", ""),
        negative_prompt=body.get("negative_prompt", ""),
        width=body.get("width", 1024),
        height=body.get("height", 1024),
        steps=body.get("steps", 20),
        cfg_scale=body.get("cfg_scale", 7.0),
        seed=body.get("seed", -1),
        init_image=init_image,
        mask_image=mask_image,
        denoising_strength=body.get("denoising_strength", 0.75),
        sampler_name=body.get("sampler_name", "euler"),
        batch_size=body.get("batch_size", 1),
    )


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  SPZ GPT Image Proxy v0.5.0")
    print("  Model: " + DEFAULT_MODEL)
    print("  Listen: " + HOST + ":" + str(PORT))
    print("  API Key: " + ("SET" if API_KEY else "NOT SET (no-key mode)"))
    print("=" * 50 + "\n")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
