from fastapi import APIRouter, Depends

from zhijing.dependencies import get_container
from zhijing.features.author.schemas import AuthorAnswer, AuthorQuestion

router = APIRouter(prefix="/author", tags=["答主.skill"])


@router.post("/ask", response_model=AuthorAnswer)
def ask(body: AuthorQuestion, container=Depends(get_container)):
    return container.author.ask(body)
