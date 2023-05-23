#!/usr/bin/env python
# This plan contains tests that demonstrate failures as well.
"""
This example shows how console output can be configured on different
levels (e.g. plan, multitest).
"""
import sys
import time

from testplan.progress_indicator.fancy import FancyProgressIndicator
from testplan.testing.multitest import MultiTest, testsuite, testcase

from testplan import test_plan
from testplan.report.testing.styles import Style


@testsuite
class AlphaSuite:
    def pre_testcase(self, name, env, result, kwargs):
        time.sleep(2)

    @testcase
    def test_equality_passing(self, env, result):
        result.equal(1, 1, description="passing equality")

    @testcase
    def test_equality_failing(self, env, result):
        result.equal(2, 1, description="failing equality")

    @testcase
    def test_membership_passing(self, env, result):
        result.contain(1, [1, 2, 3], description="passing membership")

    @testcase
    def test_membership_failing(self, env, result):
        result.contain(
            member=1,
            container={"foo": 1, "bar": 2},
            description="failing membership",
        )


@testsuite
class BetaSuite:
    def pre_testcase(self, name, env, result, kwargs):
        time.sleep(1)

    @testcase
    def test_regex_passing(self, env, result):
        result.regex.match(
            regexp="foo", value="foobar", description="passing regex match"
        )

    @testcase
    def test_regex_failing(self, env, result):
        result.regex.match(
            regexp="bar", value="foobaz", description="failing regex match"
        )


# In the example below, we have plan level configuration for console output,
# which will print out testcase names for passing tests and assertion details
# for failing ones.

# However for `Multitest('Secondary')` we have also have a lower level
# configuration for console output, which will override the plan level
# config for that particular multitest.


@test_plan(
    name="Multi-level command line output configuration example",
    stdout_style=Style(passing="testcase", failing="testcase"),
)
def main(plan):

    multi_test_1 = MultiTest(name="Primary", suites=[AlphaSuite()])
    multi_test_2 = MultiTest(
        name="Secondary",
        suites=[BetaSuite(), AlphaSuite()],
    )
    plan.add(multi_test_1)
    plan.add(multi_test_2)


if __name__ == "__main__":
    progress = FancyProgressIndicator()
    sys.exit(not main())
