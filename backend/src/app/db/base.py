from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的公共基类。

    Alembic autogenerate 通过 Base.metadata 发现模型，因此所有新建模型
    都必须继承自此类。
    """
