from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)

from testplan.event_stream import TESTPLAN_EVENTS
from testplan.event_stream.events import (
    TestProgressEvent,
    TestLevel,
    TestProgressStartEvent,
    TestProgressDoneEvent,
)
from testplan.event_stream.testplan_topics import PROGRESS


class FancyProgressIndicator:
    def __init__(self):
        self.progress = None
        self.test_progress = None
        self.test_suite_progress = None
        self.test_case_progress = None
        TESTPLAN_EVENTS.subscribe(PROGRESS, self.progress_callback)

    def progress_callback(self, topic: str, event: TestProgressEvent):

        if event.level == TestLevel.TEST:
            if isinstance(event, TestProgressStartEvent):
                self.progress = Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    TimeElapsedColumn(),
                    transient=True,
                )
                self.test_progress = self.progress.add_task(
                    event.name, total=event.num_tasks
                )
                self.progress.start()

            if isinstance(event, TestProgressDoneEvent):
                self.progress.stop()

        if event.level == TestLevel.TEST_SUITE:
            if isinstance(event, TestProgressStartEvent):
                self.test_suite_progress = self.progress.add_task(
                    event.name, total=event.num_tasks
                )

            if isinstance(event, TestProgressDoneEvent):
                self.progress.remove_task(self.test_suite_progress)

        if event.level == TestLevel.TEST_CASE:
            if isinstance(event, TestProgressStartEvent):
                self.test_case_progress = self.progress.add_task(
                    event.name, total=event.num_tasks
                )

            if isinstance(event, TestProgressDoneEvent):
                self.progress.advance(self.test_progress)
                self.progress.advance(self.test_suite_progress)
                self.progress.remove_task(self.test_case_progress)
