"""
Fake A1111 Server v0.4.0
SPZ connection protocol validator.
Listens on 127.0.0.1:7860, returns preset responses.

v0.4.0 fixes:
  - Added POST /sdapi/v1/controlnet/detect (module=none passthrough)
  - Fixed /progress state to match SD_GenProgressResponseState spec

v0.3.0 fixes:
  - Added GET /internal/ping (SPZ actual connection check endpoint)
  - Added GET /sdapi/v1/sd-models (model list)
  - Added POST /sdapi/v1/options (set model/VAE)
  - Added POST /sdapi/v1/interrupt (cancel generation)

Run: python fake_a1111_server.py
"""
import os
import sys
import json
import base64
import logging
from io import BytesIO

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import Response, JSONResponse
    import uvicorn
except ImportError:
    print("pip install fastapi uvicorn")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("fake-a1111")

app = FastAPI(title="Fake A1111", version="0.4.0")

MODELS = [
    {"title": "test-protocol-validator", "model_name": "test-protocol-validator", "hash": "abc123", "sha256": "def456", "filename": "test-protocol-validator.safetensors"},
    {"title": "gpt-image-2.5-sunburst", "model_name": "gpt-image-2.5-sunburst", "hash": "ghi789", "sha256": "jkl012", "filename": "gpt-image-2.5-sunburst.safetensors"},
]

SAMPLERS = [
    {"name": "Euler", "aliases": ["euler"], "options": {}},
    {"name": "DPM++ 2M", "aliases": ["dpmpp_2m"], "options": {}},
    {"name": "DDIM", "aliases": ["ddim"], "options": {}},
]

SCHEDULERS = [
    {"name": "Automatic", "label": "Automatic", "aliases": ["automatic"], "default_rho": 1.0, "need_inner_model": False},
    {"name": "Karras", "label": "Karras", "aliases": ["karras"], "default_rho": 1.0, "need_inner_model": False},
]

UPSCALERS = [
    {"name": "None", "model_name": "None"},
    {"name": "R-ESRGAN 4x", "model_name": "R-ESRGAN 4x"},
]

CURRENT_OPTIONS = {
    "sd_model_checkpoint": "test-protocol-validator",
    "sd_vae": "Automatic",
    "CLIP_stop_at_last_layers": 1,
}

# Task state matching SD_GenProgressResponseState spec
TASK_STATE = {
    "job": "",
    "job_count": 0,
    "sampling_step": 0,
    "sampling_steps": 0,
}


def make_test_image(w=512, h=512, color=(100, 150, 200)):
    try:
        from PIL import Image
        img = Image.new("RGB", (w, h), color)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


@app.get("/internal/ping")
async def internal_ping():
    log.info("GET /internal/ping -> SPZ connection check")
    return Response(content="OK", media_type="text/plain")


@app.get("/ping")
async def ping():
    return Response(content="OK", media_type="text/plain")


@app.get("/")
async def root():
    return {"detail": "Fake A1111 Server v0.4.0"}


@app.get("/sdapi/v1/options")
async def get_options():
    log.info("GET /options")
    return CURRENT_OPTIONS


@app.post("/sdapi/v1/options")
async def set_options(request: Request):
    body = await request.json()
    updated_keys = list(body.keys())
    for k, v in body.items():
        if k in CURRENT_OPTIONS:
            CURRENT_OPTIONS[k] = v
    log.info("POST /options -> updated: " + str(updated_keys))
    return {"status": "ok", "updated": updated_keys}


@app.get("/sdapi/v1/sd-models")
async def get_models():
    log.info("GET /sd-models -> " + str(len(MODELS)) + " models")
    return MODELS


@app.get("/sdapi/v1/samplers")
async def get_samplers():
    log.info("GET /samplers -> " + str(len(SAMPLERS)) + " samplers")
    return SAMPLERS


@app.get("/sdapi/v1/sd-schedulers")
async def get_sd_schedulers():
    log.info("GET /sd-schedulers -> " + str(len(SCHEDULERS)) + " schedulers")
    return SCHEDULERS


@app.get("/sdapi/v1/schedulers")
async def get_schedulers():
    return SCHEDULERS


@app.get("/sdapi/v1/upscalers")
async def get_upscalers():
    return UPSCALERS


@app.get("/sdapi/v1/upscale-models")
async def get_upscale_models():
    return UPSCALERS


@app.get("/sdapi/v1/progress")
async def get_progress():
    return {
        "progress": 0.0,
        "eta_relative": 0.0,
        "state": TASK_STATE,
        "current_image": "",
        "textinfo": "Idle",
    }


@app.post("/sdapi/v1/interrupt")
async def interrupt():
    global TASK_STATE
    TASK_STATE["job"] = "cancelled"
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
            content={"detail": "ControlNet module not supported. Only module=none available."}
        )


@app.post("/sdapi/v1/txt2img")
async def txt2img(request: Request):
    body = await request.json()
    w = body.get("width", 512)
    h = body.get("height", 512)
    prompt_preview = body.get("prompt", "")[:40]
    log.info("POST /txt2img: prompt=" + prompt_preview + "... size=" + str(w) + "x" + str(h))
    return {
        "images": [make_test_image(w, h)],
        "parameters": body,
        "info": json.dumps({"seed": body.get("seed", 42), "model": "test-protocol-validator"}),
    }


@app.post("/sdapi/v1/img2img")
async def img2img(request: Request):
    body = await request.json()
    w = body.get("width", 512)
    h = body.get("height", 512)
    denoise = body.get("denoising_strength", "?")
    has_mask = "mask" in body and body["mask"] is not None
    log.info("POST /img2img: denoise=" + str(denoise) + " mask=" + str(has_mask))
    return {
        "images": [make_test_image(w, h)],
        "parameters": body,
        "info": json.dumps({"seed": body.get("seed", 42), "model": "test-protocol-validator"}),
    }


if __name__ == "__main__":
    PORT = int(os.environ.get("FAKE_A1111_PORT", "7860"))
    print("\nFake A1111 Server v0.4.0 -> 127.0.0.1:" + str(PORT))
    print("  /internal/ping        <- SPZ connection check")
    print("  /sdapi/v1/options     <- GET+POST")
    print("  /sdapi/v1/sd-models   <- GET")
    print("  /sdapi/v1/samplers    <- GET")
    print("  /sdapi/v1/schedulers  <- GET")
    print("  /sdapi/v1/txt2img     <- POST")
    print("  /sdapi/v1/img2img     <- POST")
    print("  /sdapi/v1/controlnet/detect <- POST (passthrough)")
    print("  /sdapi/v1/progress    <- GET")
    print("  /sdapi/v1/interrupt   <- POST\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
