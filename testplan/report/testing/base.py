"""
Report classes that will store the test results.

Assuming we have a Testplan setup like this:
.. code-block:: python
  Testplan MyPlan
    Multitest A
      Suite A-1
        TestCase test_method_a_1_x
        TestCase test_method_a_1_y
        TestCase (parametrized, with 3 scenarios) test_method_a_1_z
      Suite A-2
        Testcase test_method_a_2_x
    Multitest B
      Suite B-1
        Testcase test_method_b_1_x
    GTest C
We will have a report tree like:
.. code-block:: python
  TestReport(name='MyPlan')
    TestGroupReport(name='A', category='Multitest')
      TestGroupReport(name='A-1', category='TestSuite')
        TestCaseReport(name='test_method_a_1_x')
        TestCaseReport(name='test_method_a_1_y')
        TestGroupReport(name='test_method_a_1_z', category='parametrization')
          TestCaseReport(name='test_method_a_1_z_1')
          TestCaseReport(name='test_method_a_1_z_2')
          TestCaseReport(name='test_method_a_1_z_3')
      TestGroupReport(name='A-2', category='TestSuite')
        TestCaseReport(name='test_method_a_2_x')
    TestGroupReport(name='B', category='MultiTest')
      TestGroupReport(name='B-1', category='TestSuite')
        TestCaseReport(name='test_method_b_1_x')
    TestGroupReport(name='C', category='GTest')
      TestCaseReport(name='<first test of Gtest>') -> can only be retrieved
                                                      after GTest is run
      TestCaseReport(name='<second test of Gtest>') -> can only be retrieved
                                                       after GTest is run
    ...
"""
import copy
import getpass
import hashlib
import itertools
import os
import platform
import sys
from collections import Counter
from typing import Dict, Optional
from typing_extensions import Self

from testplan.common.report import (
    Status,
    RuntimeStatus,
    ReportCategories,
    ExceptionLogger,
    Report,
    BaseReportGroup,
)
from testplan.testing import tagging


class TestReport(BaseReportGroup):
    """
    Report for a Testplan test run, sits at the root of the report tree.
    Only contains TestGroupReports as children.
    """

    def __init__(
        self,
        name,
        meta=None,
        attachments=None,
        information=None,
        timeout=None,
        label=None,
        **kwargs,
    ):
        self._tags_index = None
        self.meta = meta or {}
        self.label = label
        self.information = information or []
        self.resource_meta_path: Optional[str] = None
        try:
            user = getpass.getuser()
        except (ImportError, OSError):
            # if the USERNAME env variable is unset on Windows, this fails
            # with ImportError
            user = "unknown"
        self.information.extend(
            [
                ("user", user),
                ("command_line_string", " ".join(sys.argv)),
                ("python_version", platform.python_version()),
            ]
        )
        if self.label:
            self.information.append(("label", label))

        # Report attachments: Dict[dst: str, src: str].
        # Maps from destination path (relative from attachments root dir)
        # to the full source path (absolute or relative from cwd).
        self.attachments = attachments or {}
        self.timeout = timeout
        self.category = ReportCategories.TESTPLAN

        super(TestReport, self).__init__(name=name, **kwargs)

    @property
    def tags_index(self):
        """
        Root report only has tag indexes, which is only useful when
        we run searches against multiple test reports.
        (e.g Give me all test runs from all projects that have these tags)
        """
        from testplan.testing.tagging import merge_tag_dicts

        if self._tags_index is None:
            self._tags_index = merge_tag_dicts(
                *[child.tags_index for child in self]
            )
        return self._tags_index

    def propagate_tag_indices(self):
        """
        TestReport does not have native tag data,
        so it just triggers children's tag updates.
        """
        for child in self:
            child.propagate_tag_indices()

        # reset tags index, so it gets repopulated on the next call
        self._tags_index = None

    def bubble_up_attachments(self):
        """
        Attachments are saved at various levels of the report:

          * Fix spec file attached to multitests.
          * When implemented result.attach will attach files to assertions.

        This iterates through the report entries and bubbles up all the
        attachments to the top level. This top level dictionary of attachments
        will be used by Exporters to export attachments as well as the report.
        """
        for child in self:
            if getattr(child, "fix_spec_path", None):
                self._bubble_up_fix_spec(child)
            for attachment in child.attachments:
                self.attachments[attachment.dst_path] = attachment.source_path

    def _bubble_up_fix_spec(self, child):
        """Bubble up a "fix_spec_path" from a child report."""
        real_path = child.fix_spec_path
        hash_dir = hashlib.md5(real_path.encode("utf-8")).hexdigest()
        hash_path = os.path.join(
            hash_dir, os.path.basename(child.fix_spec_path)
        )
        child.fix_spec_path = hash_path
        self.attachments[hash_path] = real_path

    def _get_comparison_attrs(self):
        return super(TestReport, self)._get_comparison_attrs() + [
            "tags_index",
            "meta",
        ]

    def serialize(self):
        """
        Shortcut for serializing test report data
        to nested python dictionaries.
        """
        from .schemas import TestReportSchema

        return TestReportSchema().dump(self)

    @classmethod
    def deserialize(cls, data):
        """
        Shortcut for instantiating ``TestReport`` object (and its children)
        from nested python dictionaries.
        """
        from .schemas import TestReportSchema

        return TestReportSchema().load(data)

    def shallow_serialize(self):
        """Shortcut for shallow-serializing test report data."""
        from .schemas import ShallowTestReportSchema

        return ShallowTestReportSchema().dump(self)

    @classmethod
    def shallow_deserialize(cls, data, old_report):
        """
        Shortcut for deserializing a ``TestReport`` object from its shallow
        serialized representation.
        """
        from .schemas import ShallowTestReportSchema

        deserialized = ShallowTestReportSchema().load(data)
        deserialized.entries = old_report.entries
        deserialized._index = old_report._index

        return deserialized

    def filter(self, *functions, **kwargs) -> Self:
        """
        Tag indices are updated after filter operations.
        """
        result = super(TestReport, self).filter(*functions, **kwargs)

        # We'd like to call tag propagation before returning the root node,
        # so we rely on absence of implicit `__copy` arg to decide if we should
        # trigger tag index propagation or not. If we don't do this check
        # then tag propagation will be called for each filter call on
        # sub-nodes which is going to be a redundant operation.

        if kwargs.get("__copy", True):
            result.propagate_tag_indices()
        return result

    def inherit(self, deceased: Self) -> Self:
        self.timer = deceased.timer
        self.status_override = deceased.status_override
        self.status_reason = deceased.status_reason
        self.attachments = deceased.attachments
        self.logs = deceased.logs

        for uid in set(self.entry_uids) & set(deceased.entry_uids):
            self_ = self[uid]
            deceased_ = deceased[uid]
            if isinstance(self_, TestGroupReport) and isinstance(
                deceased_, TestGroupReport
            ):
                self_.inherit(deceased_)

        return self


class TestGroupReport(BaseReportGroup):
    """
    A middle-level container report, can contain both TestGroupReports and
    TestCaseReports.
    """

    def __init__(
        self,
        name,
        category=ReportCategories.TESTGROUP,
        tags=None,
        part=None,
        fix_spec_path=None,
        env_status=None,
        strict_order=False,
        **kwargs,
    ):
        super(TestGroupReport, self).__init__(name=name, **kwargs)

        # This will be used for distinguishing test type (Multitest, GTest
        # etc). Expected to be one of the ReportCategories enum, otherwise
        # the report node will not be correctly rendered in the UI.
        self.category = category

        self.tags = tagging.validate_tag_value(tags) if tags else {}
        self.tags_index = copy.deepcopy(self.tags)

        # A test can be split into many parts and the report of each part
        # can be hold back for merging (if necessary)
        self.part = part  # i.e. (m, n), while 0 <= m < n and n > 1
        self.part_report_lookup = {}

        self.fix_spec_path = fix_spec_path

        if self.entries:
            self.propagate_tag_indices()

        # Expected to be one of ResourceStatus, or None.
        self.env_status = env_status

        # Can be True For group report in category "testsuite"
        self.strict_order = strict_order

        self.covered_lines: Optional[dict] = None

    def __str__(self):
        return (
            f'{self.__class__.__name__}(name="{self.name}", category="{self.category}",'
            f' id="{self.uid}"), tags={self.tags or None})'
        )

    def __repr__(self):
        return (
            f'{self.__class__.__name__}(name="{self.name}", category="{self.category}",'
            f' id="{self.uid}", entries={repr(self.entries)}, tags={self.tags or None})'
        )

    def _get_comparison_attrs(self):
        return super(TestGroupReport, self)._get_comparison_attrs() + [
            "category",
            "tags",
            "tags_index",
        ]

    def append(self, item):
        """Update tag indices if item or self has tag data."""
        super(TestGroupReport, self).append(item)
        if self.tags_index or item.tags_index:
            self.propagate_tag_indices()

    def serialize(self):
        """
        Shortcut for serializing TestGroupReport data to nested python
        dictionaries.
        """
        from .schemas import TestGroupReportSchema

        return TestGroupReportSchema().dump(self)

    @classmethod
    def deserialize(cls, data):
        """
        Shortcut for instantiating ``TestGroupReport`` object
        (and its children) from nested python dictionaries.
        """
        from .schemas import TestGroupReportSchema

        return TestGroupReportSchema().load(data)

    def shallow_serialize(self):
        """Shortcut for shallow-serializing test report data."""
        from .schemas import ShallowTestGroupReportSchema

        return ShallowTestGroupReportSchema().dump(self)

    @classmethod
    def shallow_deserialize(cls, data, old_report):
        """
        Shortcut for deserializing a ``TestGroupReport`` object from its
        shallow serialized representation.
        """
        from .schemas import ShallowTestGroupReportSchema

        deserialized = ShallowTestGroupReportSchema().load(data)
        deserialized.entries = old_report.entries
        deserialized._index = old_report._index
        return deserialized

    def _collect_tag_indices(self):
        """
        Recursively collect tag indices from children (and their children etc)
        """
        tag_dicts = [self.tags]

        for child in self:
            if isinstance(child, TestGroupReport):
                tag_dicts.append(child._collect_tag_indices())
            elif isinstance(child, TestCaseReport):
                tag_dicts.append(child.tags)
        return tagging.merge_tag_dicts(*tag_dicts)

    def propagate_tag_indices(self, parent_tags=None):
        """
        Distribute native tag data onto `tags_index` attributes on the nodes
        of the test report. This distribution happens 2 ways.
        """
        tags_index = tagging.merge_tag_dicts(self.tags, parent_tags or {})

        for child in self:
            if isinstance(child, TestGroupReport):
                child.propagate_tag_indices(parent_tags=tags_index)

            elif isinstance(child, TestCaseReport):
                child.tags_index = tagging.merge_tag_dicts(
                    child.tags, tags_index
                )

        self.tags_index = tagging.merge_tag_dicts(
            tags_index, self._collect_tag_indices()
        )

    def merge(self, report, strict=True):
        """Propagate tag indices after merge operations."""
        super(TestGroupReport, self).merge(report, strict=strict)
        self.propagate_tag_indices()

    @property
    def attachments(self):
        """Return all attachments from child reports."""
        return itertools.chain.from_iterable(
            child.attachments for child in self
        )

    @property
    def hash(self):
        """
        Generate a hash of this report object, including its entries. This
        hash is used to detect when changes are made under particular nodes
        in the report tree. Since all report entries are mutable, this hash
        should NOT be used to index the report entry in a set or dict - we
        have avoided using the magic __hash__ method for this reason. Always
        use the UID for indexing purposes.

        :return: a hash of all entries in this report group.
        :rtype: ``int``
        """
        return hash(
            (
                self.uid,
                self.status,
                self.runtime_status,
                self.env_status,
                tuple(entry.hash for entry in self.entries),
                tuple(entry["uid"] for entry in self.logs),
            )
        )

    def filter(self, *functions, **kwargs) -> Self:
        """
        Tag indices are updated after filter operations.
        """
        result = super(TestGroupReport, self).filter(*functions, **kwargs)

        # We'd like to call tag propagation before returning the root node,
        # so we rely on absence of implicit `__copy` arg to decide if we should
        # trigger tag index propagation or not. If we don't do this check
        # then tag propagation will be called for each filter call on
        # sub-nodes which is going to be a redundant operation.

        if kwargs.get("__copy", True):
            result.propagate_tag_indices()
        return result

    def inherit(self, deceased: Self) -> Self:
        self.timer = deceased.timer
        self.status_override = deceased.status_override
        self.status_reason = deceased.status_reason
        self.env_status = deceased.env_status
        self.logs = deceased.logs

        for uid in set(self.entry_uids) & set(deceased.entry_uids):
            self_ = self[uid]
            deceased_ = deceased[uid]
            if isinstance(self_, TestGroupReport) and isinstance(
                deceased_, TestGroupReport
            ):
                self_.inherit(deceased_)
            elif isinstance(self_, TestCaseReport) and isinstance(
                deceased_, TestCaseReport
            ):
                self_.inherit(deceased_)

        return self


class TestCaseReport(Report):
    """
    Leaf of the report tree, contains serialized assertion / log entries.
    """

    exception_logger = ExceptionLogger

    def __init__(
        self,
        name,
        tags=None,
        category=ReportCategories.TESTCASE,
        **kwargs,
    ):
        super(TestCaseReport, self).__init__(name=name, **kwargs)

        self.tags = tagging.validate_tag_value(tags) if tags else {}
        self.tags_index = copy.deepcopy(self.tags)
        self.attachments = []
        self.category = category
        self.covered_lines: Optional[dict] = None

    def _get_comparison_attrs(self):
        return super(TestCaseReport, self)._get_comparison_attrs() + [
            "status_override",
            "timer",
            "tags",
            "tags_index",
        ]

    @property
    def passed(self) -> bool:
        """Shortcut for getting if report status should be considered passed."""
        return self.status.normalised() == Status.PASSED

    @property
    def failed(self) -> bool:
        """
        Shortcut for checking if report status should be considered failed.
        """
        return self.status <= Status.FAILED

    @property
    def unstable(self) -> bool:
        """
        Shortcut for checking if report status should be considered unstable.
        """
        return self.status.normalised() == Status.UNSTABLE

    @property
    def unknown(self) -> bool:
        """
        Shortcut for checking if report status is unknown.
        """
        return self.status.normalised() == Status.UNKNOWN

    @property
    def status(self) -> Status:
        """
        Entries in this context correspond to serialized (raw)
        assertions / custom logs in dictionary form.
        Assertion dicts will have a `passed` key
        which will be set to `False` for failed assertions.
        """
        if self.status_override:
            return self.status_override

        if self.entries:
            return self._assertions_status()

        return self._status

    @status.setter
    def status(self, new_status):
        self._status = new_status

    @property
    def runtime_status(self):
        """
        Used for interactive mode, the runtime status of a testcase may be one
        of ``RuntimeStatus``.
        """
        return self._runtime_status

    @runtime_status.setter
    def runtime_status(self, new_status):
        """
        Set the runtime status. As a special case, when a testcase is re-run
        we clear out the assertion entries from any previous run.
        """
        self._runtime_status = new_status
        if self.entries and new_status in (
            RuntimeStatus.RUNNING,
            RuntimeStatus.RESETTING,
        ):
            self.entries = []
            self._status = Status.UNKNOWN
        if new_status == RuntimeStatus.FINISHED:
            self._status = Status.PASSED  # passed if case report has no entry

    # NOTE: this is only for compatibility with the API for filtering.
    def set_runtime_status_filtered(
        self,
        new_status: str,
        entries: Dict,
    ) -> None:
        """
        Alternative setter for the runtime status of an entry, here it is
            equivalent to simply setting the runtime status.

        :param new_status: new runtime status to be set
        :param entries: tree-like structure of entries names, unused, but
            needed for current API compatibility
        """
        self.runtime_status = new_status

    def _assertions_status(self):
        # entries already serialized here
        for entry in self:
            if entry.get("passed") is False:
                return Status.FAILED
        return Status.PASSED

    def merge(self, report, strict=True):
        """
        TestCaseReport merge overwrites everything in place, as assertions of
        a test case won't be split among different runners. For some special
        test cases, choose the one whose status is of higher precedence.
        """
        self._check_report(report)
        if (
            self.category == ReportCategories.SYNTHESIZED
            and self.status.precede(report.status)
        ):
            return

        self.status_override = Status.precedent(
            [self.status_override, report.status_override]
        )
        self.runtime_status = report.runtime_status
        self.logs = report.logs
        self.entries = report.entries
        self.timer = report.timer
        self.status_reason = report.status_reason

    def flattened_entries(self, depth):
        """Need to take assertion groups into account."""

        def flatten_dicts(dicts, _depth):
            """Recursively flatten serialized entry list."""
            result = []
            for d in dicts:
                result.append((_depth, d))
                if d["type"] == "Group" or d["type"] == "Summary":
                    result.extend(flatten_dicts(d["entries"], _depth + 1))
            return result

        return flatten_dicts(self.entries, depth)

    def serialize(self):
        """
        Shortcut for serializing test report data
        to nested python dictionaries.
        """
        from .schemas import TestCaseReportSchema

        return TestCaseReportSchema().dump(self)

    @classmethod
    def deserialize(cls, data):
        """
        Shortcut for instantiating ``TestCaseReport`` object
        from nested python dictionaries.
        """
        from .schemas import TestCaseReportSchema

        return TestCaseReportSchema().load(data)

    @property
    def hash(self):
        """
        Generate a hash of this report object, including its entries. This
        hash is used to detect when changes are made under particular nodes
        in the report tree. Since all report entries are mutable, this hash
        should NOT be used to index the report entry in a set or dict - we
        have avoided using the magic __hash__ method for this reason. Always
        use the UID for indexing purposes.

        :return: a hash of all entries in this report group.
        :rtype: ``int``
        """
        return hash(
            (
                self.uid,
                self.status,
                self.runtime_status,
                tuple(id(entry) for entry in self.entries),
                tuple(entry["uid"] for entry in self.logs),
            )
        )

    def xfail(self, strict):
        """
        Override report status for test that is marked xfail by user
        :param strict: whether consider XPASS as failure
        """
        if self.failed:
            self.status_override = Status.XFAIL
        elif self.passed:
            if strict:
                self.status_override = Status.XPASS_STRICT
            else:
                self.status_override = Status.XPASS

    @property
    def counter(self):
        """
        Return counts for current status.
        """
        counter = Counter(
            {
                Status.PASSED.to_json_compatible(): 0,
                Status.FAILED.to_json_compatible(): 0,
                "total": 0,
            }
        )
        counter.update({self.status.to_json_compatible(): 1, "total": 1})
        return counter

    def pass_if_empty(self):
        """Mark as PASSED if this testcase contains no entries."""
        if not self.entries:
            self._status = Status.PASSED

    def inherit(self, deceased: Self) -> Self:
        self.timer = deceased.timer
        self.runtime_status = deceased.runtime_status
        self.status = deceased.status
        self.status_override = deceased.status_override
        self.status_reason = deceased.status_reason
        self.attachments = deceased.attachments
        self.logs = deceased.logs
        self.entries = deceased.entries
        return self
