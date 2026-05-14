from sqlalchemy import BigInteger, Boolean, Column, Integer, String

from app.db.session import Base


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    # `code` is the routing key: "world" | "economy" | ...
    # Stored as category_code for backward DB compatibility
    category_code = Column(String, unique=True, nullable=False)

    telegram_chat_id = Column(BigInteger, unique=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    @property
    def code(self) -> str:
        return self.category_code

    @code.setter
    def code(self, value: str) -> None:
        self.category_code = value
