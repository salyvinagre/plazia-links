"""Cross-resource ownership checks used by link mutations."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.folder_service import get_folder


async def verify_folder_workspace(
    db: AsyncSession,
    folder_id: str | None,
    workspace_id: str,
) -> None:
    if folder_id is None:
        return
    folder = await get_folder(db, folder_id)
    if folder is None or folder.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Folder not found")
