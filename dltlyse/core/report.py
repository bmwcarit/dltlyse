# Copyright (C) 2016. BMW Car IT GmbH. All rights reserved.
"""Reporting for dltlyse"""

from collections import Counter

xunit_template = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<testsuite name="{testsuite_name}" tests="{number_of_tests}" errors="{number_of_errors}" '
    'failures="{number_of_failures}" skip="{number_of_skipped}">'
    '{testcases}'
    '</testsuite>'
)

xunit_tc_template = dict(
    error=(
        '<testcase classname="{classname}" name="{testname}" time="0">'
        '<error type="error" message="{message}"></error>'
        '<system-out><![CDATA[{stdout}]]></system-out>'
        '{attach}'
        '</testcase>'
    ),
    failure=(
        '<testcase classname="{classname}" name="{testname}" time="0">'
        '<failure type="failure" message="{message}"></failure>'
        '<system-out><![CDATA[{stdout}]]></system-out>'
        '{attach}'
        '</testcase>'
    ),
    skipped=(
        '<testcase classname="{classname}" name="{testname}" time="0">'
        '<skipped type="skip" message="{message}"></skipped>'
        '<system-out><![CDATA[{stdout}]]></system-out>'
        '{attach}'
        '</testcase>'
    ),
    success=(
        '<testcase classname="{classname}" name="{testname}" time="0">'
        '<system-out><![CDATA[{stdout}]]></system-out>'
        '{attach}'
        '</testcase>'
    ),
)

attachment_template = ('[[ATTACHMENT|{filename}]]')


def xunit_render(result):
    """Render the result into XUnit chunk"""
    kwargs = result.__dict__
    kwargs["attach"] = "".join([attachment_template.format(filename=x) for x in kwargs.get("attach", [])])
    return xunit_tc_template[result.state].format(**kwargs)


class Result(object):
    """Class representing a single testcase result"""
    def __init__(self, classname="Unknown", testname="Unknown", state="success", stdout="", stderr="", message="",
                 attach=None):
        self.classname = classname
        self.testname = testname
        self.state = state
        self.stdout = stdout
        self.stderr = stderr
        self.message = message
        if not attach:
            attach = []
        self.attach = attach

    def __repr__(self):
        return repr(self.__dict__)

    def __eq__(self, other):
        return self.__dict__ == other.__dict__


class XUnitReport(object):
    """Template class producing report in xUnit format"""

    def __init__(self, outfile=False, testsuite_name="dltlyse"):
        self.results = []
        self.outfile = outfile
        self.testsuite_name = testsuite_name

    def add_results(self, results):
        """Adds a result to the report"""
        self.results.extend(results)

    def render(self):
        """Renders an XUnit report"""
        kwargs = {}
        kwargs["testsuite_name"] = self.testsuite_name
        counts = Counter(x.state for x in self.results)
        kwargs["testcases"] = "\n".join(xunit_render(x) for x in self.results)
        kwargs["number_of_errors"] = counts["error"]
        kwargs["number_of_failures"] = counts["failure"]
        kwargs["number_of_skipped"] = counts["skipped"]
        kwargs["number_of_tests"] = len(self.results)
        report = xunit_template.format(**kwargs)
        if self.outfile:
            with open(self.outfile, "w") as reportfile:
                reportfile.write(report.encode("utf8"))
