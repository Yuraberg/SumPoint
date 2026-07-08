"""Shared FastAPI dependencies for the API routers."""
from typing import Annotated

from fastapi import Depends

from app.api.auth import get_current_user
from app.models.user import User

CurrentUser = Annotated[User, Depends(get_current_user)]
