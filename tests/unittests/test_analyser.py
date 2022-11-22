"""Tests for core analyser parts of dltlyse."""
from contextlib import contextmanager
import os
import signal
import threading
import time
from typing import List, Tuple, Union
from unittest import TestCase
from unittest.mock import ANY, call, MagicMock, patch

import pytest

from dlt.dlt import cDLT_FILE_NOT_OPEN_ERROR, DLT_EMPTY_FILE_ERROR, DLTMessage
from dlt.core import API_VER as DLT_VERSION_STR
from dltlyse.core.analyser import DLTAnalyser, DLTLifecycle, DltlysePluginCollector
from dltlyse.core.utils import (
    create_temp_dlt_file,
    dlt_example_stream,
    single_random_corrupt_dlt_message,
    single_random_dlt_message,
    start_dlt_message,
)
from tests.unittests.plugins.helpers import MockDLTMessage


try:
    DLT_VERSION = tuple(int(num) for num in DLT_VERSION_STR.split("."))
except:  # noqa: E722
    DLT_VERSION = (2, 18, 5)


@contextmanager
def fake_analyser():
    """A fake DLTAnalyser"""
    with patch("dltlyse.core.analyser.get_plugin_classes", return_value=[]):
        analyser = DLTAnalyser()
        analyser.load_plugins([])

        yield analyser


@contextmanager
def fake_analyser_with_run_analyse_mock(dlt_msgs, plugin=None):
    """Helper function to mock internal functions for DLTAnalyser.run_analyse"""
    cls_name = "dltlyse.core.analyser.DLTAnalyser"

    with patch("{}.get_filters".format(cls_name)), patch("signal.signal"), patch(
        "dltlyse.core.analyser.dlt.load", return_value=dlt_msgs
    ), patch("{}.process_buffer".format(cls_name)) as mock_process_buffer, patch(
        "{}.generate_reports".format(cls_name)
    ), patch(
        "{}.setup_lifecycle".format(cls_name), return_value=DLTLifecycle("MGHS", 1)
    ) as mock_setup_lifecycle, patch(
        "{}.end_lifecycle".format(cls_name)
    ) as mock_end_lifecycle:
        with fake_analyser() as analyser:
            mocks = {
                "end_lifecycle": mock_end_lifecycle,
                "process_buffer": mock_process_buffer,
                "setup_lifecycle": mock_setup_lifecycle,
            }

            if plugin:
                analyser.plugin_collector.msg_plugins = {("APID", "CTID"): (plugin,)}
                analyser.plugin_collector.apid_plugins = {"APID": (plugin,)}
                analyser.plugin_collector.ctid_plugins = {"CTID": (plugin,)}
                analyser.plugin_collector.greedy_plugins = (plugin,)

            yield (analyser, mocks)


class FakePlugin(object):
    """Fake plugin, only for testing purpose"""

    def __init__(self, plugin_name, message_filters):  # type: (str, Union[str, List[Tuple[str, str]]]) -> None
        self.plugin_name = plugin_name  # type: str
        self.message_filters = message_filters  # type: (Union[str, List[Tuple[str, str]]])
        self.call_count = 0

    def __call__(self, msg):  # type: (DLTMessage) -> None
        self.call_count += 1

    def get_plugin_name(self):  # type: () -> str
        """Get a fake plugin name"""
        return self.plugin_name


class FakePluginException(FakePlugin):
    """Fake plugin, only for testing purpose"""

    def __call__(self, msg):
        super(FakePluginException, self).__call__(msg)

        raise Exception("Fake exception")


def test_load_plugins():
    """Test plugin loading"""
    obj = DLTAnalyser()
    obj.load_plugins([])

    assert "ExtractFilesPlugin" in obj.show_plugins()
    assert "ContextPlugin" in obj.show_plugins()


def test_load_plugins_specific():
    """Test specific plugin loading"""
    obj = DLTAnalyser()
    obj.load_plugins([], plugins=["ExtractFilesPlugin"])

    assert "ExtractFilesPlugin" in obj.show_plugins()
    assert "ContextPlugin" not in obj.show_plugins()


def test_dont_load_manually_executed_plugins():
    """Test that a manually-executed plugin isn't automatically loaded"""
    obj = DLTAnalyser()
    obj.load_plugins([])

    assert "HeavyLifecyclesAnalyzer" not in obj.show_plugins()


def test_analyse_file_sanity():
    """Simulate test run of the dltlyse with invalid dlt trace files"""
    obj = DLTAnalyser()

    obj.start_lifecycle = MagicMock()
    obj.end_lifecycle = MagicMock()
    obj.process_message = MagicMock()
    obj.generate_reports = MagicMock()
    xunit = MagicMock()

    file_not_exist = "mock.dlt"
    file_empty = create_temp_dlt_file(empty=True)
    file_valid = create_temp_dlt_file(stream=dlt_example_stream)

    obj.load_plugins([], plugins=["ExtractFilesPlugin", "TestSysErrorPlugin"])
    obj.run_analyse([file_not_exist, file_empty, file_valid], xunit, True, False)

    assert file_valid not in obj.file_exceptions
    assert cDLT_FILE_NOT_OPEN_ERROR in obj.file_exceptions[file_not_exist]
    assert DLT_EMPTY_FILE_ERROR in obj.file_exceptions[file_empty]


def test_corrupt_msg_live():
    """Simulate test run of the dltlyse live with corrupt message"""

    def send_stop_signal(pid):
        """Send a stop signal to the live run"""
        time.sleep(0.1)
        os.kill(pid, signal.SIGINT)

    # Test with exactly MAX_BUFFER_SIZE MSGS and No Start
    obj = DLTAnalyser()
    obj.get_filters = MagicMock(return_value=[])
    obj.start_lifecycle = MagicMock()
    obj.end_lifecycle = MagicMock()
    obj.generate_reports = MagicMock()
    xunit = MagicMock()
    stop_thread = threading.Thread(target=send_stop_signal, args=(os.getpid(),))

    random_msgs = bytearray()
    for i in range(60):
        if i % 25 == 0:
            random_msgs.extend(single_random_corrupt_dlt_message)
        elif i % 15 == 0:
            random_msgs.extend(start_dlt_message)
        else:
            random_msgs.extend(single_random_dlt_message)

    file1 = create_temp_dlt_file(stream=random_msgs)

    stop_thread.start()
    obj.run_analyse([file1], xunit, True, True)

    assert obj.start_lifecycle.mock_calls == [
        call("MGHS", 0),
        call("MGHS", 1),
        call("MGHS", 2),
        call("MGHS", 3),
    ]

    assert obj.end_lifecycle.call_count == 4
    if DLT_VERSION < (2, 18, 5):
        assert obj.dlt_file.corrupt_msg_count == 3
    assert obj.generate_reports.mock_calls == [call(xunit, "dltlyse")]


def test_init_plugin_collector():
    """Test to init the plugin collector"""
    with patch("dltlyse.core.analyser.DltlysePluginCollector.init_plugins") as mock_init:
        with fake_analyser():
            mock_init.assert_called_once()


@pytest.mark.parametrize(
    "plugins,expected_filters",
    [
        ([FakePlugin("fake_plugin", "all")], None),
        (
            [
                FakePlugin("fake_plugin", [("APID", "CTID")]),
                FakePlugin("fake_plugin", [("APID1", "CTID1")]),
                FakePlugin("fake_plugin", [("APID", "CTID")]),
            ],
            [("APID", "CTID"), ("APID1", "CTID1")],
        ),
    ],
)
def test_check_get_filters(plugins, expected_filters):
    """Check filters"""
    with fake_analyser() as analyser:
        analyser.plugins = plugins

        flts = analyser.get_filters()
        if isinstance(flts, list):
            assert sorted(flts) == sorted(expected_filters)
        else:
            assert flts == expected_filters


@pytest.mark.parametrize(
    "msg_buffer",
    [
        [],
        [MagicMock(), MagicMock()],
    ],
)
def test_check_process_buffer(msg_buffer):
    """Check process buffer"""

    with fake_analyser() as analyser, patch("dltlyse.core.analyser.DLTAnalyser.process_message") as mock_process:
        analyser._buffered_traces = msg_buffer

        analyser.process_buffer()

        assert mock_process.call_count == len(msg_buffer)
        assert not analyser._buffered_traces


def test_run_analyse_init_lifecycle():
    """Test to init lifecycle without lifecycle start messages"""
    dlt_msgs = [
        MockDLTMessage(apid="APID", ctid="CTID"),
        MockDLTMessage(apid="APID", ctid="CTID"),
    ]

    with fake_analyser_with_run_analyse_mock(dlt_msgs) as (analyser, mocks):
        analyser.run_analyse(["/tmp/no-such-file"], MagicMock(), False, False)

        mocks["setup_lifecycle"].assert_called_with(dlt_msgs[0], lifecycle_id=0, process_buffer=True)


def test_run_analyse_init_lifecycle_with_msg():
    """Test to init lifecycle with a lifecycle start message"""
    dlt_msgs = [
        MockDLTMessage(apid="DLTD", ctid="INTM", payload="Daemon launched. Starting to output traces..."),
    ]
    with fake_analyser_with_run_analyse_mock(dlt_msgs) as (analyser, mocks):
        analyser.run_analyse(["/tmp/no-such-file"], MagicMock(), False, False)

        mocks["setup_lifecycle"].assert_called_with(msg=dlt_msgs[0], lifecycle_id=1)


def test_run_analyse_init_lifecycle_with_msgs():
    """Test to init lifecycle with lifecycle start messages"""
    dlt_msgs = [
        MockDLTMessage(apid="DLTD", ctid="INTM", payload="Daemon launched. Starting to output traces..."),
        MockDLTMessage(apid="DLTD", ctid="INTM", payload="Daemon launched. Starting to output traces..."),
    ]
    with fake_analyser_with_run_analyse_mock(dlt_msgs) as (analyser, mocks):
        analyser.run_analyse(["/tmp/no-such-file"], MagicMock(), False, False)

        mocks["end_lifecycle"].assert_called_with(ANY, 2)


def test_run_analyse_call_plugin():
    """Test to dispatch messages to plugins"""
    plugin = FakePlugin("fake_plugin", None)

    dlt_msgs = [
        MockDLTMessage(apid="APID", ctid="CTID"),
    ]

    with fake_analyser_with_run_analyse_mock(dlt_msgs, plugin) as (analyser, _):
        analyser.run_analyse(["/tmp/no-such-file"], MagicMock(), False, False)

        assert plugin.call_count == 4


def test_run_analyse_call_plugin_with_exception():
    """Test to handle plugin's exceptions"""
    plugin = FakePluginException("fake_plugin", None)

    dlt_msgs = [
        MockDLTMessage(apid="APID", ctid="CTID"),
    ]

    with patch("dltlyse.core.analyser.make_plugin_exception_message") as mock_exception:
        with fake_analyser_with_run_analyse_mock(dlt_msgs, plugin) as (analyser, _):
            analyser.run_analyse(["/tmp/no-such-file"], MagicMock(), False, False)

            assert mock_exception.call_count == 4


def test_run_analyse_buffer_traces():
    """Test to append traces to buffer"""
    dlt_msgs = [
        MockDLTMessage(apid="DA1", ctid="DC1", payload="[connection_info ok] connected \00\00\00\00"),
        MockDLTMessage(ecuid="XORA"),
    ]

    with fake_analyser_with_run_analyse_mock(dlt_msgs) as (analyser, mocks):
        analyser.run_analyse(["/tmp/no-such-file"], MagicMock(), False, False)

        assert len(analyser._buffered_traces) == 2
        mocks["process_buffer"].assert_called()


def test_plugin_collector_convert_dict_value_tuple():
    """Test to convert a list of plugins to a tuple of plugins"""
    collector = DltlysePluginCollector()
    # pylint: disable=protected-access
    assert collector._convert_dict_value_tuple({"abc": ["1", "2", "3"]}) == {"abc": ("1", "2", "3")}


def test_plugin_collector_dispatch():
    """Test to dispatch plugins by message filters"""
    test_plugins = {
        "greedy": FakePlugin("greedy", "all"),
        "apid_ctid": FakePlugin("apid_ctid", [("APID", "CTID")]),
        "apid": FakePlugin("apid", [("APID", "")]),
        "ctid": FakePlugin("ctid", [("", "CTID")]),
    }

    collector = DltlysePluginCollector()
    collector._dispatch_plugins(test_plugins.values())  # pylint: disable=protected-access

    assert collector.msg_plugins == {("APID", "CTID"): (test_plugins["apid_ctid"],)}
    assert collector.apid_plugins == {"APID": (test_plugins["apid"],)}
    assert collector.ctid_plugins == {"CTID": (test_plugins["ctid"],)}
    assert collector.greedy_plugins == (test_plugins["greedy"],)


@pytest.mark.parametrize(
    "plugins,expected_msg",
    [
        ([FakePlugin("fake_plugin", "not-valid")], "Invalid message filter setting: fake_plugin - not-valid"),
        ([FakePlugin("fake_plugin", [])], "Message filter should not empty: fake_plugin - []"),
        (
            [FakePlugin("fake_plugin", [("APID", "CTID"), ("APID", "")])],
            "Duplicated message filter setting: fake_plugin - [('APID', 'CTID'), ('APID', '')]",
        ),
        (
            [FakePlugin("fake_plugin", [("APID", "CTID"), ("", "CTID")])],
            "Duplicated message filter setting: fake_plugin - [('APID', 'CTID'), ('', 'CTID')]",
        ),
    ],
)
def test_check_plugin_collector_check_plugin_msg_filters(plugins, expected_msg):
    """Check the message filter format"""
    with pytest.raises(ValueError) as err:
        DltlysePluginCollector()._check_plugin_msg_filters(plugins)  # pylint: disable=protected-access

    assert str(err.value) == expected_msg


@pytest.mark.parametrize(
    "plugins,expected_value",
    [
        ((FakePlugin("fake_plugin", [("APID", "CTID")]),), ["fake_plugin"]),
        ({"APID": (FakePlugin("fake_plugin", [("APID", "CTID")]),)}, {"APID": ["fake_plugin"]}),
    ],
)
def test_check_plugin_collector_convert_plugin_obj_to_name(plugins, expected_value):
    """Check that the conversion from plugin objects to plugin names is correct"""
    # pylint: disable=protected-access
    assert DltlysePluginCollector()._convert_plugin_obj_to_name(plugins) == expected_value


def test_plugin_collector_print_plugin_collections():
    """Test to print the plugin dispatching information"""
    with patch("dltlyse.core.analyser.DltlysePluginCollector._convert_plugin_obj_to_name") as mock_convert:
        DltlysePluginCollector()._print_plugin_collections()  # pylint: disable=protected-access

        assert mock_convert.call_count == 4


def test_plugin_collector_init_plugins():
    """Test to init plugin dispatching information"""
    cls_name = "dltlyse.core.analyser.DltlysePluginCollector"
    with patch("{}._check_plugin_msg_filters".format(cls_name)) as mock_check, patch(
        "{}._dispatch_plugins".format(cls_name)
    ) as mock_dispatch, patch("{}._print_plugin_collections".format(cls_name)) as mock_print:
        DltlysePluginCollector().init_plugins([])

        mock_check.assert_called_with([])
        mock_dispatch.assert_called_with([])
        mock_print.assert_called_with()
