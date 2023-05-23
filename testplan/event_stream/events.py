from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Event(BaseModel):
    created: datetime = Field(default_factory=datetime.utcnow)


class TestLevel(Enum):
    TEST = 1
    TEST_SUITE = 2
    TEST_CASE = 3


class TestProgressEvent(Event):
    level: TestLevel
    name: str


class TestProgressStartEvent(TestProgressEvent):
    num_tasks: Optional[int] = None


class TestProgressDoneEvent(TestProgressEvent):
    result: str = None
