from io import BytesIO
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse

from app.core.database import get_db, SessionLocal
from app.core.config import settings
from app.core.security import validate_jwt_token
from app.services import ChatService
from app.helpers import ExcelTemplateBulider, validate_headers

router = APIRouter()


@router.post("/init_llm_analyzes/")
async def init_llm_analyzes(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):

    """
    example body
    {
    'product_name': 'test', 
    'product_url': 'https://www.chmarine.com/international-cruiser-250-antifoul-3L/', 
    'extra_context': 'test', 
    'model': 'gpt-5-nano'}
    """

    return StreamingResponse(
        ChatService(openai_api_key=settings.OPENAI_API_KEY).start_analysis(
            db, body, user.get("tenant_id")
        ),
        media_type="application/x-ndjson",
    )


CHAT_TEMPLATE_HEADERS = [
    {
        "id": "product_name",
        "identity": "Product Name",
        "required": False,
        "comment": "Name of the Product",
    },
    {
        "id": "brand",
        "identity": "Brand",
        "required": False,
        "comment": "Brand",
    },
    {
        "id": "mpn",
        "identity": "MPN",
        "required": False,
        "comment": "MPN",
    },
    {
        "id": "ean",
        "identity": "EAN",
        "required": False,
        "comment": "EAN",
    },
    {
        "id": "upc",
        "identity": "UPC",
        "required": False,
        "comment": "UPC",
    },
    {
        "id": "category",
        "identity": "Category",
        "required": False,
        "comment": "Category",
    },
    {
        "id": "taxonomy",
        "identity": "Taxonomy",
        "required": False,
        "comment": "Taxonomy",
    },
]

CHAT_EXAMPLE_DATA = [
    {
        "product_name": "Premium Brake Pads",
        "brand": "StopSafe",
        "mpn": "BP-9923-X",
        "ean": "4006381333931",
        "upc": "884616012345",
        "category": "Braking System",
        "taxonomy": "Auto Parts > Brakes > Brake Pads",
    },
]


@router.get("/bulk-upload-template/")
async def generate_chat_template(
    user: dict = Depends(validate_jwt_token),
):
    """api endpoint that streams bulk upload template for chat"""

    builder = ExcelTemplateBulider(
        headers=CHAT_TEMPLATE_HEADERS,
        sheet_name="chat_template",
        data=CHAT_EXAMPLE_DATA,
        example=True,
    )

    wb = builder.build()

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachement; filename=industry_template.xlsx"},
    )


# @router.post("/bulk-upload/")
# async def upload_excel(
#     file: UploadFile = File(...),
#     user: dict = Depends(validate_jwt_token),
#     db: AsyncSession = Depends(get_db),
# ):
#     try:
#         # -------- Step 1: Read and parse the file --------
#         contents = await file.read()
#         excel_file = BytesIO(contents)

#         workbook = load_workbook(excel_file)
#         sheet = workbook.active
#         data = list(sheet.iter_rows(values_only=True))

#         if not data:
#             raise HTTPException(status_code=400, detail="Excel file is empty")

#         headers = data[0]
#         rows = data[1:]

#         # -------- Step 2: Validate Headers --------
#         validation = await validate_headers(headers, CHAT_TEMPLATE_HEADERS)

#         if validation:
#             raise HTTPException(
#                 status_code=400,
#                 detail=f"Missing Columns: {', '.join(validation)}, kindly use the template file",
#             )

#         # -------- Step 3: Initialize tracking variables --------
#         created = 0
#         updated = 0
#         error_rows = []

#         # ==========================================
#         # TODO: PLACE YOUR BUSINESS LOGIC HERE
#         # - Clean & validate rows in memory
#         # - Fetch existing database records
#         # - Compare and build insert/update instances
#         # - db.add_all() / db.commit()
#         # ==========================================

#         # -------- Step 4: Handle error file generation if necessary --------
#         if error_rows:
#             error_headers = [
#                 *CHAT_TEMPLATE_HEADERS,
#                 {
#                     "id": "error",
#                     "identity": "Error",
#                     "error": True,
#                     "comment": "Reason for the failure",
#                 },
#             ]

#             builder = ExcelTemplateBulider(
#                 headers=error_headers,
#                 sheet_name="chat_bulk_import_errors",
#                 data=error_rows,
#             )

#             wb = builder.build()
#             buffer = BytesIO()
#             wb.save(buffer)
#             buffer.seek(0)

#             return StreamingResponse(
#                 buffer,
#                 media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#                 headers={
#                     "Content-Disposition": "attachment; filename=chat_bulk_import_errors.xlsx"
#                 },
#             )

#         # -------- Step 5: Return successful response --------
#         return {
#             "created": created,
#             "updated": updated,
#             "errors": 0,
#         }

#     except HTTPException:
#         # Re-raise FastAPIs HTTPExceptions so they don't get caught by the generic Exception handler
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Import Failed: {str(e)}")




async def process_row_background_task(
    row_data: dict, tenant_id: int, user_id: int, session_factory
):
    """Worker function acting as the isolated background task boundary per row.

    Since generators ('yield') cannot be awaited directly inside background tasks,
    this driver consumes the streaming outputs and handles errors safely per task execution context.
    """
    # Create an isolated database session block per row context loop to avoid session contention
    async with session_factory() as db:
        try:
            chat_service = ChatService()
            # Consume generator results safely without breaking execution loops
            async for log in chat_service.start_analysis(
                db=db, data=row_data, tenant_id=tenant_id, user_id=user_id
            ):
                # Optionally stream or log pipeline events to external cloud monitoring engines
                pass
        except Exception as task_err:
            print(
                f"[Row Worker Error] Failed processing for row identification parameters {row_data}: {str(task_err)}"
            )


@router.post("/bulk-upload/")
async def upload_excel(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: dict = Depends(validate_jwt_token),
):
    try:
        contents = await file.read()
        excel_file = BytesIO(contents)

        workbook = load_workbook(excel_file)
        sheet = workbook.active
        data = list(sheet.iter_rows(values_only=True))

        if not data:
            raise HTTPException(status_code=400, detail="Excel file is empty")

        # Map header string inputs down to cleaner tracking coordinates
        headers = [str(h).strip().lower() if h else "" for h in data[0]]
        rows = data[1:]

        validation = await validate_headers(headers, CHAT_TEMPLATE_HEADERS)

        if validation:
            raise HTTPException(
                status_code=400,
                detail=f"Missing Columns: {', '.join(validation)}. Kindly use the explicit corporate template file.",
            )

        # Extraction parameters context
        tenant_id = user.get("tenant_id", 1)
        user_id = user.get("user_id")

        # Session factory tracker used to generate clean isolated context wrappers inside background loops
        # This prevents session collisions across concurrently executing background workers
        session_factory = SessionLocal

        task_count = 0

        # -------- Parse Matrix Rows Into Background Queue Payload --------
        for row in rows:
            if not any(row):  # Skip completely empty rows
                continue

            # Zip explicit header labels cleanly alongside values matrix entries
            row_dict = dict(zip(headers, row))

            # Clean blank string parameters or text inputs safely
            cleaned_payload = {
                "product_name": (
                    str(row_dict["product_name"]).strip()
                    if row_dict.get("product_name")
                    else None
                ),
                "product_url": (
                    str(row_dict["product_url"]).strip()
                    if row_dict.get("product_url")
                    else None
                ),
                "sku": str(row_dict["sku"]).strip() if row_dict.get("sku") else None,
                "ean": str(row_dict["ean"]).strip() if row_dict.get("ean") else None,
                "upc": str(row_dict["upc"]).strip() if row_dict.get("upc") else None,
                "mpn": str(row_dict["mpn"]).strip() if row_dict.get("mpn") else None,
                "brand_name": (
                    str(row_dict["brand_name"]).strip()
                    if row_dict.get("brand_name")
                    else "Generic/Multi-Brand"
                ),
                "countries": (
                    str(row_dict["countries"]).strip()
                    if row_dict.get("countries")
                    else "United States of America"
                ),
                "extra_context": (
                    str(row_dict["extra_context"]).strip()
                    if row_dict.get("extra_context")
                    else ""
                ),
                "model": (
                    str(row_dict["model"]).strip()
                    if row_dict.get("model")
                    else "gpt-4o"
                ),
            }

            # Append the processing run straight to background execution queue loops
            background_tasks.add_task(
                process_row_background_task,
                row_data=cleaned_payload,
                tenant_id=tenant_id,
                user_id=user_id,
                session_factory=session_factory,
            )
            task_count += 1

        return {
            "status": "Accepted",
            "message": f"Successfully scheduled {task_count} product validation workflows in the background.",
            "processed_rows": task_count,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Bulk process initialization failed: {str(e)}"
        )
