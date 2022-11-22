"""Tests for CallBacksAndReport plugin for dltlyse."""
import types
from unittest import TestCase

from unittest.mock import Mock, call  # pylint: disable=no-name-in-module,import-error

from dltlyse.core.plugin_base import CallBacksAndReportPlugin, dlt_callback
from tests.unittests.plugins.helpers import MockDLTMessage


class CallBacksAndReportPluginForTesting(CallBacksAndReportPlugin):
    """Define the abstract method report, only for testing."""

    def report(self):
        """See above: empty implementation."""


class TestCallBacksAndReportPluginBase(TestCase):
    """Base class for CallBacksAndReportPlugin descendants."""

    plugin_class = None  # The CallBacksAndReportPlugin descendant class to be instantiated.

    def setUp(self):
        self.init_and_add_callbacks()  # Create a default instance of the class, and sets-up a mock.

    def init_and_add_callbacks(self, *callbacks):
        """ "Helper to register callbacks to the plugin.

        It creates a fresh instance of the CallBacksAndReportPlugin descendant class, registers
        the given callbacks, and creates a mock for the write_to_domain_file method.

        Args:
            callbacks(list/tuple of callbacks): the list/tuple of callbacks to be registered.
        """
        # pylint: disable=not-callable
        self.plugin = self.plugin_class()  # Creates a fresh instance of the plugin_class.

        for callback in callbacks:
            # Creates a method of the plugin_class, for the instance which we created.
            func = types.MethodType(callback, self.plugin)

            # Plugs such method to the instance.
            setattr(self.plugin, callback.__name__, func)

        # We need to re-execute it, to register the above callbacks.
        self.plugin.collect_and_register_callbacks()

        # Creates a mock for this method.
        self.mock = self.plugin.write_to_domain_file = Mock()


class TestDltCallbackDecorator(TestCase):
    """dlt_callback decorator unit tests."""

    def check_filters(self, func, app_id="", ctx_id=""):
        """Checks if the dlt callback has defined the specific filters.

        Args:
            func(func): a function (method) which should be decorated with dlt_callback.
            kwargs(dict): a dictionary with the filters that should be defined, and their values.
        """
        filter_condition = getattr(func, "filter_condition", None)
        self.assertIsNotNone(filter_condition)
        self.assertEqual(filter_condition, (app_id, ctx_id))

    def test_no_decoration_applied(self):
        """Tests that a non-decorated function doesn't contain filter criteria."""

        def callback(self, message):
            """Callback invoked when the expected trace is matched."""
            pass

        self.assertFalse(hasattr(callback, "filter_condition"))

    def test_no_filter_defined(self):
        """Tests that no filter is defined."""

        @dlt_callback()
        def callback(self, message):
            """Callback invoked when the expected trace is matched."""
            pass

        self.check_filters(callback)

    def test_only_app_id_defined(self):
        """Tests that only the app_id is defined."""

        @dlt_callback("SYS")
        def callback(self, message):
            """Callback invoked when the expected trace is matched."""
            pass

        self.check_filters(callback, "SYS")

    def test_only_ctx_id_defined(self):
        """Tests that only the ctx_id is defined."""

        @dlt_callback(None, "JOUR")
        def callback(self, message):
            """Callback invoked when the expected trace is matched."""
            pass

        self.check_filters(callback, ctx_id="JOUR")

    def test_app_id_and_ctx_id_defined(self):
        """Tests that app_id and ctx_id are defined."""

        @dlt_callback("SYS", "JOUR")
        def callback(self, message):
            """Callback invoked when the expected trace is matched."""
            pass

        self.check_filters(callback, "SYS", "JOUR")


class TestCallBacksAndReportPlugin(TestCallBacksAndReportPluginBase):
    """CallBacksAndReport plugin unit tests."""

    plugin_class = CallBacksAndReportPluginForTesting

    def test_report_filename(self):
        """Tests that the report filename is the name of the class + .txt."""
        self.assertEqual(self.plugin.report_filename(), "call_backs_and_report_plugin_for_testing.txt")
        self.assertEqual(self.mock.call_count, 0)

    def test_prepare_report(self):
        """Tests that prepare_report is called when a report is generated."""
        self.plugin.prepare_report = prepare_report_mock = Mock()
        self.assertEqual(self.plugin.get_report(), "No report is generated!")
        self.assertEqual(prepare_report_mock.call_count, 1)
        self.assertEqual(self.mock.call_count, 0)

    def test_no_report(self):
        """Tests that no report is generated if there was no data collected."""
        self.assertEqual(self.plugin.get_report(), "No report is generated!")
        self.assertEqual(self.mock.call_count, 0)

    def test_text_file_report(self):
        """Tests that a text file report is generated, when some data is collected."""

        @dlt_callback("SYS", "JOUR")
        def systemd_callback(self, message):
            """Callback invoked when the expected trace is matched."""
            self.report_output = "Something was found!"

        self.init_and_add_callbacks(systemd_callback)
        self.plugin(
            MockDLTMessage(
                apid="SYS",
                ctid="JOUR",
                payload="2017/01/31 14:03:33.154124 1.454729 kernel: Warning: "
                "sd: u=dri-permissions.path, inactive_exit=548934",
            )
        )

        # Since we are using a mock for write_to_domain_file, the mock returns another Mock instance
        # to the caller.
        self.assertIsInstance(self.plugin.get_report(), Mock)

        self.assertEqual(self.mock.call_count, 1)
        self.assertEqual(
            self.mock.call_args_list[0], call("call_backs_and_report_plugin_for_testing.txt", "Something was found!")
        )

    def test_collect_and_register_callbacks(self):  # pylint: disable=invalid-name
        """Tests that collect_and_register_callbacks detects and registers the callbacks which were
        decorated with dlt_callback."""

        @dlt_callback("SYS", "JOUR")
        def systemd_callback(self, message):
            """Callback invoked when the expected trace is matched."""
            pass

        self.init_and_add_callbacks(systemd_callback)
        self.assertEqual(len(self.plugin.dlt_callbacks), 1)
        filter_condition, callbacks = self.plugin.dlt_callbacks.popitem()
        self.assertEqual(filter_condition, ("SYS", "JOUR"))
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0].__name__, systemd_callback.__name__)

    def test_add_callback_from_template_function(self):  # pylint: disable=invalid-name
        """Tests that add_callback_from_template_function adds a callback, deriving it from a template function."""

        def mtee_callback(message, app_id=None, ctx_id=None, userdata=None):
            """Callback invoked when the expected mtee trace is matched."""
            pass

        self.plugin.add_callback_from_template_function(mtee_callback, "SYS", "JOUR", "TEST")
        self.assertEqual(len(self.plugin.dlt_callbacks), 1)
        filter_condition, callbacks = self.plugin.dlt_callbacks.popitem()
        self.assertEqual(filter_condition, ("SYS", "JOUR"))
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0].keywords, {"app_id": "SYS", "ctx_id": "JOUR", "userdata": "TEST"})
        self.assertEqual(callbacks[0].func.__name__, mtee_callback.__name__)  # pylint: disable=no-member

    def test_calling_callbacks(self):
        """Tests that all registered callbacks are correctly called when a message matches their
        filter conditions."""

        @dlt_callback("SYS", "JOUR")
        def systemd_callback(self, message):
            """Callback invoked when a systemd trace is matched."""
            matches.append(message)

        @dlt_callback("LTM", "MAIN")
        def version_callback(self, message):
            """Callback invoked when the ltm trace is matched."""
            matches.append(message)

        def mtee_callback(message, app_id=None, ctx_id=None, userdata=None):
            """Callback invoked when the expected mtee trace is matched."""
            payload = str(message.payload_decoded)
            if payload == userdata:
                matches.append(message)

        matches = []
        self.init_and_add_callbacks(systemd_callback, version_callback)
        self.plugin.add_callback_from_template_function(mtee_callback, "MTEE", "MTEE", "START")

        systemd_message = MockDLTMessage(apid="SYS", ctid="JOUR", payload="systemd!")
        self.plugin(systemd_message)
        main_message = MockDLTMessage(apid="LTM", ctid="MAIN", payload="main!")
        self.plugin(main_message)
        self.plugin(MockDLTMessage(apid="DA1", ctid="DC1", payload="New lifecycle!"))
        self.plugin(MockDLTMessage(apid="MTEE", ctid="MTEE", payload="STOP"))
        mtee_message = MockDLTMessage(apid="MTEE", ctid="MTEE", payload="START")
        self.plugin(mtee_message)

        self.assertEqual(len(matches), 3)
        self.assertEqual(matches[0], systemd_message)
        self.assertEqual(matches[1], main_message)
        self.assertEqual(matches[2], mtee_message)
