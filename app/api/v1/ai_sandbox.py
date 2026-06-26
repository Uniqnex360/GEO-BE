import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()


async def generate(product_name: str):

    yield json.dumps(
        {"type": "status", "color": "green", "message": "Started generating..."}
    ) + "\n"

    await asyncio.sleep(1)

    yield json.dumps(
        {"type": "status", "color": "green", "message": "Searching projects..."}
    ) + "\n"

    await asyncio.sleep(2)

    yield json.dumps(
        {"type": "status", "color": "red", "message": "Project not found for query 1"}
    ) + "\n"

    await asyncio.sleep(2)

    yield json.dumps(
        {"type": "status", "color": "green", "message": "Generating GEO report..."}
    ) + "\n"

    await asyncio.sleep(3)

    yield json.dumps(
        {
            "type": "result",
            "content": """
# GEO Report

Your product appears in 12 sources.

## Recommendations

- Improve title
- Add FAQ
- Add comparison page
""",
        }
    ) + "\n"


@router.post("/generate/")
async def generate_geo(body: dict):
    return StreamingResponse(
        generate(body["product_name"]),
        media_type="application/x-ndjson",
    )
