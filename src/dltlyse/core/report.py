# Copyright (C) 2022-23. BMW Car IT GmbH. All rights reserved.
"""Reporting for dltlyse"""
from collections import Counter
import datetime as dt
import logging
import socket
import xml.etree.ElementTree as etree


ATTACHMENT_TEMPLATE = "[[ATTACHMENT|{filename}]]"

TEST_CASE_RESULT_TYPE = {
    "success": "success",
    "error": "error",
    "failure": "failure",
    "skipped": "skip",
}

logger = logging.getLogger(__name__)  # pylint: disable=invalid-name


class Metadata(object):
    """Store the metadata of result

    The metadata is a dict. It can contain any type of data, but it presents with `str()` finally.

    The class is internally used for `class Result`. Normally you should not use the class directly.
    """

    def __init__(self, metadata=None):
        self.metadata = metadata or {}

    def _render_xml(self, node, metadata):
        """Real implementation for render_xml

        If parses self.metadata and transforms it to a xml element. If the type of value is a dict, it parses it
        recursively. Otherwise, it will convert the value with `str()`
        """
        for key, value in sorted(metadata.items(), key=lambda keyvalue: keyvalue[0]):
            item = etree.SubElement(node, "item", name=key)
            if isinstance(value, dict):
                self._render_xml(item, value)
            else:
                item.text = str(value)

    def render_xml(self):
        """Return a xml element to present metadata

        The function is a wrapper function for `Metadata._render_xml`, you can get more details from it.
        """
        if not self.metadata or not isinstance(self.metadata, dict):
            return None

        root = etree.Element("metadata")
        self._render_xml(root, self.metadata)

        return root


class Result(object):
    """Class representing a single testcase result"""

    def __init__(
        self,
        classname="Unknown",
        testname="Unknown",
        state="success",
        stdout="",
        stderr="",
        message="",
        metadata=None,
        attach=None,
        timestamp=None,
    ):
        self.classname = classname
        self.testname = testname
        self.state = state
        self.stdout = stdout
        self.stderr = stderr
        self.message = message
        if not attach:
            attach = []
        self.attach = attach

        self.metadata = Metadata(metadata)
        self.timestamp = str(dt.datetime.now(dt.timezone.utc)) if timestamp is None else str(timestamp)

    def __repr__(self):
        return repr(self.__dict__)

    def __eq__(self, other):
        self_dict = self.__dict__.copy()
        del self_dict["metadata"]

        other_dict = other.__dict__.copy()
        del other_dict["metadata"]

        return self_dict == other_dict

    def render_xml(self):
        """Return a xml element to present test result"""
        if self.state not in TEST_CASE_RESULT_TYPE:
            logger.warning("Not supported for the test state: %s - plugin: %s", self.state, self.classname)
            self.state = "error"

        # Prepare test case root
        root = etree.Element(
            "testcase", classname="dltlyse." + self.classname, name=self.testname, time="0", timestamp=self.timestamp
        )

        # Set attachment
        root.text = "".join(ATTACHMENT_TEMPLATE.format(filename=filename) for filename in self.attach)

        # If the result is not success, output state and error message
        if self.state != "success":
            root.append(etree.Element(self.state, type=TEST_CASE_RESULT_TYPE[self.state], message=self.message))

        # Output stdout
        stdout = etree.SubElement(root, "system-out")
        stdout.text = str(self.stdout)

        # Add metadata
        metadata = self.metadata.render_xml()
        if metadata is not None:
            root.append(metadata)

        return root


class XUnitReport(object):
    """Template class producing report in xUnit format"""

    def __init__(
        self, outfile="", testsuite_name="dltlyse", hardware=None, software=None, hostname=None, id_=None, package=None
    ):
        self.results = []
        self.outfile = outfile
        self.testsuite_name = testsuite_name
        self.hardware = hardware
        self.software = software
        self.hostname = socket.gethostname() if hostname is None else hostname
        self.id = id_
        self.package = package

    def add_results(self, results):
        """Adds a result to the report"""
        self.results.extend(results)

    def _generate_summary(self):
        """Count the number of stats for test cases"""
        counts = Counter(x.state for x in self.results)
        return {
            "number_of_errors": str(counts["error"]),
            "number_of_failures": str(counts["failure"]),
            "number_of_skipped": str(counts["skipped"]),
            "number_of_tests": str(len(self.results)),
        }

    def render_xml(self):
        """Return a xml element to present report"""
        summary = self._generate_summary()
        root_attributes = {
            "name": self.testsuite_name,
            "tests": summary["number_of_tests"],
            "errors": summary["number_of_errors"],
            "failures": summary["number_of_failures"],
            "skip": summary["number_of_skipped"],
            "hostname": self.hostname,
        }
        if self.id:
            root_attributes["id"] = str(self.id)
        if self.package:
            root_attributes["package"] = str(self.package)

        root = etree.Element("testsuite", **root_attributes)

        if self.hardware and isinstance(self.hardware, dict):
            etree.SubElement(root, "hardware", self.hardware)
        if self.software and isinstance(self.software, dict):
            etree.SubElement(root, "software", self.software)

        result_elements = []
        for result in self.results:
            try:
                element = result.render_xml()
                result_elements.append(element)
            except Exception as err:  # pylint: disable=broad-except
                logger.error("Render result error: %s - %s", result, err)

        root.extend(result_elements)

        return root

    def render(self):
        """Renders a XUnit report to file"""
        if not self.outfile:
            return

        # Generate the xml element tree
        tree = etree.ElementTree(self.render_xml())

        # Write to file
        with open(self.outfile, "wb") as report_file:
            tree.write(report_file, encoding="UTF-8", xml_declaration=True, method="xml")
