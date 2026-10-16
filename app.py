"""FastAPI 应用入口：服务端渲染单页，无前后端分离。

直接运行：
    python app.py
或：
    uvicorn app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import logging


from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import (
    BASE_DIR,
    CODE_PRESETS,
    DEFAULT_CODE,
    DEFAULT_FREQUENCY,
    DEFAULT_THRESHOLD,
    FREQUENCIES,
    SWING_THRESHOLDS,
)
from src import cache
from src.fetcher import FetchError, normalize_code
from src.report import get_payload

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("stock-cycle")

STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"

app = FastAPI(title="长期走势 · 回撤 · 牛熊周期分析", docs_url="/docs")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _short_code(code: str) -> str:
    return code[2:] if len(code) >= 8 and code[:2] in ("sh", "sz") else code


def _bare_code(code: str) -> str:
    """去掉 sh/sz 前缀，仅保留 6 位数字代码，用于输入框回显。"""
    return code[2:] if code[:2] in ("sh", "sz") and len(code) >= 8 else code


def _render(request: Request, code: str, refresh: bool, since: str | None):
    display_code = code
    payload = None
    error = None
    try:
        code = normalize_code(code)
        display_code = code
        payload = get_payload(code, refresh=refresh, since=since, logger=logger.info)
    except (FetchError, ValueError) as exc:
        logger.warning("取数失败：%s", exc)
        error = str(exc)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "code": display_code,
            "code_display": _bare_code(display_code),
            "payload": payload,
            "error": error,
            "presets": CODE_PRESETS,
            "thresholds": SWING_THRESHOLDS,
            "frequencies": FREQUENCIES,
            "default_frequency": DEFAULT_FREQUENCY,
            "default_threshold": DEFAULT_THRESHOLD,
            "since": since or "",
            "title": (
                f"{_short_code(display_code)}（对数）走势、回撤与牛熊周期"
                if payload
                else f"{display_code} 数据获取失败"
            ),
        },
    )


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    code: str = Query(DEFAULT_CODE),
    refresh: int = Query(0, description="1 表示强制刷新数据"),
    since: str | None = Query(None, description="自定义基准日 YYYY-MM-DD"),
):
    return _render(request, code, bool(refresh), since)


@app.post("/api/refresh")
def api_refresh(code: str = Query(DEFAULT_CODE)):
    """强制清缓存并重新抓取，返回最新元信息。"""
    try:
        normalized = normalize_code(code)
        cache.clear(normalized)
        payload = get_payload(normalized, refresh=True, logger=logger.info)
        return JSONResponse({"ok": True, "meta": payload["meta"]})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)


@app.get("/api/data")
def api_data(
    code: str = Query(DEFAULT_CODE),
    since: str | None = Query(None),
):
    """纯 JSON 接口，便于外部程序调用。"""
    try:
        payload = get_payload(code, refresh=False, since=since, logger=logger.info)
        return JSONResponse(payload)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)


@app.get("/api/health")
def api_health():
    return {"ok": True}


if __name__ == "__main__":
    import os

    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
