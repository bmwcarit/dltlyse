# Copyright (C) 2017, BMW Car IT GmbH. All rights reserved.
"""Tests for core analyser parts of dltlyse."""
import os
import signal
import threading
import time

from unittest import TestCase

from mock import Mock, call

from dltlyse.core.analyser import DLTAnalyser
from dltlyse.core.utils import (dlt_example_stream, create_temp_dlt_file, single_random_dlt_message,
                                start_dlt_message, single_random_corrupt_dlt_message)
from dlt.dlt import cDLT_FILE_NOT_OPEN_ERROR, DLT_EMPTY_FILE_ERROR


class AnalyserTests(TestCase):
    """Tests of the main dltlyse analyser class"""

    def test_load_plugins(self):
        """Test plugin loading"""
        obj = DLTAnalyser()
        obj.load_plugins([])

        self.assertIn("ExtractFilesPlugin", obj.show_plugins())
        self.assertIn("TestSysErrorPlugin", obj.show_plugins())

    def test_load_plugins_specific(self):
        """Test specific plugin loading"""
        obj = DLTAnalyser()
        obj.load_plugins([], plugins=["ExtractFilesPlugin"])

        self.assertIn("ExtractFilesPlugin", obj.show_plugins())
        self.assertNotIn("TestSysErrorPlugin", obj.show_plugins())

    def test_dont_load_manually_executed_plugins(self):  # pylint: disable=invalid-name
        """Test that a manually-executed plugin isn't automatically loaded"""
        obj = DLTAnalyser()
        obj.load_plugins([])

        self.assertNotIn("HeavyLifecyclesAnalyzer", obj.show_plugins())

    def test_load_plugins_exclude(self):
        """Test blacklisting of plugin loading"""
        obj = DLTAnalyser()
        obj.load_plugins([], exclude=["TestSysErrorPlugin"])

        self.assertIn("ExtractFilesPlugin", obj.show_plugins())
        self.assertNotIn("TestSysErrorPlugin", obj.show_plugins())

    def test_analyse_file_sanity(self):
        """Simulate test run of the dltlyse with invalid dlt trace files"""
        obj = DLTAnalyser()

        obj.start_lifecycle = Mock()
        obj.end_lifecycle = Mock()
        obj.process_message = Mock()
        obj.generate_reports = Mock()
        xunit = Mock()

        file_not_exist = "mock.dlt"
        file_empty = create_temp_dlt_file(empty=True)
        file_valid = create_temp_dlt_file(stream=dlt_example_stream)

        obj.load_plugins([], plugins=["TestSysErrorPlugin"])
        obj.run_analyse([file_not_exist, file_empty, file_valid], xunit, True, False)

        self.assertNotIn(file_valid, obj.file_exceptions)
        self.assertIn(cDLT_FILE_NOT_OPEN_ERROR, obj.file_exceptions[file_not_exist])
        self.assertIn(DLT_EMPTY_FILE_ERROR, obj.file_exceptions[file_empty])

    def test_corrupt_msg_live(self):
        """ Simulate test run of the dltlyse live with corrupt message"""

        def send_stop_signal(pid):
            """ Send a stop signal to the live run """
            time.sleep(0.1)
            os.kill(pid, signal.SIGINT)

        # Test with exactly MAX_BUFFER_SIZE MSGS and No Start
        obj = DLTAnalyser()
        obj.get_filters = Mock(return_value=[])
        obj.start_lifecycle = Mock()
        obj.end_lifecycle = Mock()
        obj.process_message = Mock()
        obj.generate_reports = Mock()
        xunit = Mock()
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

        self.assertEqual(
            obj.start_lifecycle.mock_calls,
            [
                call('MGHS', 0), call('MGHS', 1), call('MGHS', 2), call('MGHS', 3),
            ],
        )
        self.assertEqual(obj.process_message.call_count, 57)
        self.assertEqual(obj.end_lifecycle.call_count, 4)
        self.assertEqual(obj.dlt_file.corrupt_msg_count, 3)
        self.assertEqual(obj.generate_reports.mock_calls, [call(xunit, "dltlyse")])
