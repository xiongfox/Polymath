"""Excel 上传触发 Wiki 构建。"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from agent.bundle import create_agent_bundle, invalidate_agent_bundle
from api.schemas import WikiBuildResponse

# 将 src 加入 path 以导入 excel2md
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from excel2md_museum_index import WIKI_ROOT, build_wiki_from_excel  # noqa: E402

RAW_UPLOAD_DIR = Path(WIKI_ROOT) / "raw" / "uploads"


def save_uploaded_excel(content: bytes, original_filename: str) -> Path:
    RAW_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_filename).suffix.lower()
    if suffix not in {".xls", ".xlsx"}:
        raise ValueError("仅支持 .xls / .xlsx 文件")
    safe_name = f"{uuid.uuid4().hex}{suffix}"
    dest = RAW_UPLOAD_DIR / safe_name
    dest.write_bytes(content)
    return dest


def build_wiki_from_upload(
    file_bytes: bytes,
    filename: str,
    *,
    museum_name: str | None = None,
) -> WikiBuildResponse:
    excel_path = save_uploaded_excel(file_bytes, filename)
    result = build_wiki_from_excel(
        str(excel_path),
        museum_name=museum_name,
    )
    invalidate_agent_bundle()
    create_agent_bundle(force_reload=True)

    return WikiBuildResponse(
        success=True,
        message="Wiki 构建完成",
        museum_name=result["museum_name"],
        total_rows=result["total_rows"],
        relic_md_count=result["relic_md_count"],
        hall_md_count=result["hall_md_count"],
        paths=result["paths"],
        failed_relics=result.get("failed_relics") or [],
        failed_halls=result.get("failed_halls") or [],
    )
