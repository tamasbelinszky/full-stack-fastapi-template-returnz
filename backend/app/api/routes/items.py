import uuid
from typing import Any, Literal

from returnz import Err, Ok, Result, do, require
from returnz_fastapi import HttpError, ResultRouter
from sqlmodel import Session, col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Item,
    ItemCreate,
    ItemPublic,
    ItemsPublic,
    ItemUpdate,
    Message,
    User,
)

router = ResultRouter(prefix="/items", tags=["items"])


# Typed errors — carry their HTTP status + tag, and show up in /docs (unlike a
# raised HTTPException, which FastAPI can't document).
class ItemNotFound(HttpError):
    status_code = 404
    tag: Literal["item_not_found"] = "item_not_found"


class NotEnoughPermissions(HttpError):
    status_code = 403
    tag: Literal["not_enough_permissions"] = "not_enough_permissions"


# "Fetch + authorize" lived (copy-pasted) in three routes; now it lives once, as
# a Result. Errors are values, not raises.
def get_owned_item(
    *, session: Session, current_user: User, id: uuid.UUID
) -> Result[Item, ItemNotFound | NotEnoughPermissions]:
    item = session.get(Item, id)
    if item is None:
        return Err(ItemNotFound())
    if not current_user.is_superuser and item.owner_id != current_user.id:
        return Err(NotEnoughPermissions())
    return Ok(item)


@do
def update_owned_item(
    *, session: Session, current_user: User, id: uuid.UUID, item_in: ItemUpdate
) -> Result[Item, ItemNotFound | NotEnoughPermissions]:
    item = require(get_owned_item(session=session, current_user=current_user, id=id))
    item.sqlmodel_update(item_in.model_dump(exclude_unset=True))
    session.add(item)
    session.commit()
    session.refresh(item)
    return Ok(item)


@do
def delete_owned_item(
    *, session: Session, current_user: User, id: uuid.UUID
) -> Result[Message, ItemNotFound | NotEnoughPermissions]:
    item = require(get_owned_item(session=session, current_user=current_user, id=id))
    session.delete(item)
    session.commit()
    return Ok(Message(message="Item deleted successfully"))


@router.get("/", response_model=ItemsPublic)
def read_items(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve items.
    """
    if current_user.is_superuser:
        count_statement = select(func.count()).select_from(Item)
        count = session.exec(count_statement).one()
        statement = (
            select(Item).order_by(col(Item.created_at).desc()).offset(skip).limit(limit)
        )
        items = session.exec(statement).all()
    else:
        count_statement = (
            select(func.count())
            .select_from(Item)
            .where(Item.owner_id == current_user.id)
        )
        count = session.exec(count_statement).one()
        statement = (
            select(Item)
            .where(Item.owner_id == current_user.id)
            .order_by(col(Item.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        items = session.exec(statement).all()

    items_public = [ItemPublic.model_validate(item) for item in items]
    return ItemsPublic(data=items_public, count=count)


@router.get("/{id}", response_model=ItemPublic, summary="Get item by ID")
def read_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Result[Item, ItemNotFound | NotEnoughPermissions]:
    return get_owned_item(session=session, current_user=current_user, id=id)


@router.post("/", response_model=ItemPublic)
def create_item(
    *, session: SessionDep, current_user: CurrentUser, item_in: ItemCreate
) -> Any:
    """
    Create new item.
    """
    item = Item.model_validate(item_in, update={"owner_id": current_user.id})
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.put("/{id}", response_model=ItemPublic, summary="Update an item")
def update_item(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    item_in: ItemUpdate,
) -> Result[Item, ItemNotFound | NotEnoughPermissions]:
    return update_owned_item(
        session=session, current_user=current_user, id=id, item_in=item_in
    )


@router.delete("/{id}", summary="Delete an item")
def delete_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Result[Message, ItemNotFound | NotEnoughPermissions]:
    return delete_owned_item(session=session, current_user=current_user, id=id)
