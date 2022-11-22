"""Test plugin_metadata decorator and xunit report functions"""
import xml.etree.ElementTree as etree
import inspect

from nose.tools import assert_true, assert_greater_equal, eq_
import six

if six.PY2:
    from mock import patch, mock_open
else:
    from unittest.mock import patch, mock_open  # pylint: disable=no-name-in-module,import-error

from dltlyse.core.plugin_base import Plugin, plugin_metadata
from dltlyse.core.report import logger, Metadata, Result, XUnitReport


def _equal_xml_tree(root, other):  # pylint: disable=too-many-return-statements
    """Real implementation for equal_xml_tree"""
    if root is None or other is None:
        return False

    if root.tag != other.tag:
        return False

    if root.text and other.text and root.text != other.text:
        return False

    if len(tuple(root)) != len(tuple(other)):
        return False

    if dict(root.attrib) != dict(other.attrib):
        return False

    for root_child, other_child in zip(root, other):
        if not _equal_xml_tree(root_child, other_child):
            return False

    return True


def equal_xml_tree(root, other):
    """Compare the two xml trees are equal or not"""

    def to_node(node):
        """Convert str/element type to element type"""
        return etree.fromstring(node) if isinstance(node, str) else node

    return _equal_xml_tree(to_node(root), to_node(other))


# pylint: disable=missing-docstring
class TestNoMetadataPlugin(Plugin):
    def __call__(self, message):
        pass

    def report(self):
        pass


@plugin_metadata(type="test", function="monitor")
class TestMetadataPlugin(TestNoMetadataPlugin):
    """TestMetadataPlugin-first-line

    TestMetadataPlugin-description
    """


@plugin_metadata(function="logging", extra="extra")
class TestMetadataLoggingPlugin(TestMetadataPlugin):
    """TestMetadataLoggingPlugin-first-line

    TestMetadataLoggingPlugin-description
    """


@plugin_metadata(type="test", function="report")
class TestPlugin(TestNoMetadataPlugin):
    """Test-for-report

    Get full description here.
    """


def generate_test_result(attach=None, extra=""):
    """Prepare test result data and xml string"""
    attach = attach or []

    result = Result(
        classname="TestPlugin",
        testname="TestPlugin-shot-description",
        state="success",
        stdout="TestPlugin-stdoutput",
        message="TestPlugin-success-message",
        attach=attach,
    )

    xml_str = (
        '<testcase classname="dltlyse.TestPlugin" name="TestPlugin-shot-description" time="0">'
        "{}"
        "<system-out>TestPlugin-stdoutput</system-out>"
        "{}"
        "</testcase>"
    ).format("".join("[[ATTACHMENT|{}]]".format(filename) for filename in attach), extra)

    return result, xml_str


def test_plugin_no_metadata():
    """Tests that plugin metadata is not set without plugin_metadata decorator"""
    eq_(TestNoMetadataPlugin.__name__, "TestNoMetadataPlugin")
    eq_(hasattr(TestNoMetadataPlugin, "plugin_metadata"), False)
    if six.PY2:
        eq_(inspect.getdoc(TestNoMetadataPlugin), None)
    else:
        eq_(inspect.getdoc(TestNoMetadataPlugin), "dltlyse Plugin base class")


def test_plugin_metadata_base_class():
    """Tests that plugin metadata is set correctly."""
    eq_(TestMetadataPlugin.__name__, "TestMetadataPlugin")
    eq_(hasattr(TestMetadataPlugin, "plugin_metadata"), True)
    eq_(TestMetadataPlugin.plugin_metadata, {"type": "test", "function": "monitor"})
    eq_(inspect.getdoc(TestMetadataPlugin), "TestMetadataPlugin-first-line\n\nTestMetadataPlugin-description")


def test_plugin_metadata_derived_class():  # pylint: disable=invalid-name
    """Tests that plugin metadata is set correctly for derived class."""
    eq_(TestMetadataLoggingPlugin.__name__, "TestMetadataLoggingPlugin")
    eq_(hasattr(TestMetadataLoggingPlugin, "plugin_metadata"), True)
    eq_(TestMetadataLoggingPlugin.plugin_metadata, {"type": "test", "function": "logging", "extra": "extra"})
    eq_(
        inspect.getdoc(TestMetadataLoggingPlugin),
        "TestMetadataLoggingPlugin-first-line\n\nTestMetadataLoggingPlugin-description",
    )


def test_plugin_add_result_no_metadata():  # pylint: disable=invalid-name
    """Tests that the result is added correctly without metadata."""
    plugin = TestNoMetadataPlugin()
    plugin.add_result(state="success", message="Test successfully", stdout="test-stdout")

    results = plugin.get_results()
    eq_(len(results), 1)

    result = results[0]
    eq_(result.classname, "TestNoMetadataPlugin")
    eq_(result.testname, "")
    eq_(result.state, "success")
    eq_(result.message, "Test successfully")
    eq_(result.metadata.metadata, {"docstring": ""})


def test_plugin_add_result():
    """Tests that the result is added correctly."""
    plugin = TestPlugin()
    plugin.add_result(state="success", message="Test successfully", stdout="test-stdout")

    results = plugin.get_results()
    eq_(len(results), 1)

    result = results[0]
    eq_(result.classname, "TestPlugin")
    eq_(result.testname, "Test-for-report")
    eq_(result.state, "success")
    eq_(result.message, "Test successfully")
    eq_(
        result.metadata.metadata,
        {"type": "test", "function": "report", "docstring": "Test-for-report\n\nGet full description here."},
    )


def test_metadata_render_default():
    """Tests that metadata xml is None by default"""
    meta = Metadata()
    eq_(meta.render_xml(), None)


def test_metadata_render_wrong_type():
    """Tests that metadata xml is None when the metadata type is not dict"""
    meta = Metadata([])
    eq_(meta.render_xml(), None)


def test_metadata_render_normal():
    """Tests that metadata xml is rendered correctly."""
    meta = Metadata({"type": "test", "function": "monitor"})
    assert_true(
        equal_xml_tree(
            meta.render_xml(), '<metadata><item name="function">monitor</item><item name="type">test</item></metadata>'
        )
    )


def test_metadata_render_recursive():
    """Tests that metadata xml is rendered correctly and recursively."""
    meta = Metadata({"type": "test", "function": "monitor", "traceability": {"JIRA": "No exist"}})
    assert_true(
        equal_xml_tree(
            meta.render_xml(),
            (
                "<metadata>"
                '<item name="function">monitor</item>'
                '<item name="traceability">'
                '<item name="JIRA">No exist</item>'
                "</item>"
                '<item name="type">test</item>'
                "</metadata>"
            ),
        )
    )


def test_result_equal():
    result = Result()
    other = Result(metadata={"key": "should-not-have-effect"})

    eq_(result, other)


def test_result_render_xml_error_state():  # pylint: disable=invalid-name
    """Test the warning message when the test state is undefined."""
    result = Result(classname="noclass", state="nostate")

    with patch.object(logger, "warning") as logger_mock:
        result.render_xml()

        logger_mock.assert_called_with("Not supported for the test state: %s - plugin: %s", "nostate", "noclass")
        eq_(result.state, "error")


def test_result_render_xml_fail():
    """Tests that result is rendered when the state is error."""
    state = "error"
    state_type = "error"

    result = Result(
        classname="TestPlugin",
        testname="TestPlugin-shot-description",
        state=state,
        stdout="TestPlugin-stdoutput",
        message="TestPlugin-{}-message".format(state),
    )

    assert_true(
        equal_xml_tree(
            result.render_xml(),
            (
                '<testcase classname="dltlyse.TestPlugin" name="TestPlugin-shot-description" time="0">'
                '<{state} message="TestPlugin-{state}-message" type="{state_type}"/>'
                "<system-out>TestPlugin-stdoutput</system-out>"
                "</testcase>"
            ).format(state=state, state_type=state_type),
        )
    )


def test_result_render_xml_success():
    """Tests that result is rendered when the state is success."""
    result, excepted = generate_test_result()
    assert_true(equal_xml_tree(result.render_xml(), excepted))


def test_result_render_xml_with_metadata():  # pylint: disable=invalid-name
    """Tests that result is rendered with metadata"""
    result, excepted = generate_test_result(extra="<metadata/>")

    with patch("dltlyse.core.report.Metadata.render_xml", return_value=etree.Element("metadata")):
        assert_true(equal_xml_tree(result.render_xml(), excepted))


def test_result_render_xml_with_attachment():  # pylint: disable=invalid-name
    """Tests that result is rendered with attachment"""
    result, excepted = generate_test_result(attach=["test.csv"])
    assert_true(equal_xml_tree(result.render_xml(), excepted))


def test_result_render_xml_with_metadata_and_attachment():  # pylint: disable=invalid-name
    """Tests that result is rendered with metadata and attachment"""
    result, excepted = generate_test_result(attach=["test.csv"], extra="<metadata/>")

    with patch("dltlyse.core.report.Metadata.render_xml", return_value=etree.Element("metadata")):
        assert_true(equal_xml_tree(result.render_xml(), excepted))


def test_xunit_rerport_summary():
    """Tests that the statistics of test state are correct."""
    xunit_report = XUnitReport()
    xunit_report.add_results(
        [Result(state="success"), Result(state="failure"), Result(state="skipped"), Result(state="error")]
    )

    eq_(
        xunit_report._generate_summary(),  # pylint: disable=protected-access
        {"number_of_errors": "1", "number_of_failures": "1", "number_of_skipped": "1", "number_of_tests": "4"},
    )


def test_xunit_report_render_xml():
    """Tests that xunit report is rendered correctly."""
    xunit_report = XUnitReport()
    xunit_report.add_results([Result()])

    with patch("dltlyse.core.report.Result.render_xml", return_value=etree.Element("testcase")):
        assert_true(
            equal_xml_tree(
                xunit_report.render_xml(),
                '<testsuite errors="0" failures="0" name="dltlyse" skip="0" tests="1"><testcase/></testsuite>',
            )
        )


def test_xunit_report_not_render():
    """Tests that xunit report is not written with an invalid filename."""
    xunit_report = XUnitReport()

    with patch("dltlyse.core.report.open", mock_open()) as mocked_file:
        xunit_report.render()

        mocked_file().write.assert_not_called()


def test_xunit_report_render():
    """Tests that xunit report is written to file correctly."""
    xunit_report = XUnitReport()
    xunit_report.outfile = "mocked-file"

    with patch("dltlyse.core.report.XUnitReport.render_xml", return_value=etree.Element("testsuite")):
        with patch("dltlyse.core.report.open", mock_open()) as mocked_file:
            xunit_report.render()

            assert_greater_equal(mocked_file().write.call_count, 1)

            write_xml = "".join(args[0].decode() for args, _ in mocked_file().write.call_args_list)
            eq_(write_xml, "<?xml version='1.0' encoding='UTF-8'?>\n<testsuite />")
