# Copyright (C) 2016. BMW Car IT GmbH. All rights reserved.
"""DLT file analyser"""

from __future__ import print_function

import logging
import time
import traceback
import os.path
import signal
import sys
from contextlib import contextmanager
import six

from dlt import dlt

from dltlyse.core.report import XUnitReport, Result
from dltlyse.core.plugin_base import Plugin


# pylint: disable= too-many-nested-blocks, no-member

logger = logging.getLogger(__name__)
stdoutlogger = logging.getLogger("summary")
stdoutlogger.addHandler(logging.StreamHandler(sys.stdout))

DEFAULT_PLUGINS_DIRS = [
    os.path.join(os.path.dirname(__file__), "../plugins"),  # installation folder
    # e.g. /usr/bin/pythonX.X/site-packages/dltlyse/plugins
    os.path.join(os.getcwd(), "plugins"),  # plugins folder in current working directory
]

# Traces to buffer since they might be stored before lifecycle start message
buffer_matches = [
    {"apid": "DA1", "ctid": "DC1", "payload_decoded": "[connection_info ok] connected \00\00\00\00"},
    {"ecuid": "XORA"},
]
MAX_BUFFER_SIZE = 50

DLT_LIFECYCLE_START = {
    "apid": "DLTD",
    "ctid": "INTM",
    "payload_decoded": "Daemon launched. Starting to output traces...",
}


class DLTLifecycle(object):
    """Single DLT lifecycle"""

    def __init__(self, ecu_id, lifecycle_id, dltfile=None):
        self.ecu_id = ecu_id
        self.dltfile = dltfile
        self.lifecycle_id = lifecycle_id
        self._first_msg = None
        self._last_msg = None

    def set_first_msg(self, msg):
        """Set the first msg
        explicitly needed for old dlt-atlas scripts

        :param DLTMessage msg: The message to be set as the first
        """
        self._first_msg = msg

    def set_last_msg(self, msg):
        """Set the first msg
        explicitly needed for old dlt-atlas scripts

        :param DLTMessage msg: The message to be set as the last
        """
        self._last_msg = msg

    def __getitem__(self, index):
        """Get either the first or last msg in this lifecycle
        explicitly needed for old dlt-atlas scripts

        :param int index: Index to either get first or last msg
        """
        if index == 0:
            if self._first_msg:
                return self._first_msg
            else:
                logger.error("Set first msg of lifecycle before using lifecycle object")
                raise ValueError()
        elif index == -1:
            if self._last_msg:
                return self._last_msg
            else:
                logger.error("Set last msg of lifecycle before using lifecycle object")
                raise ValueError()
        else:
            logger.error("Access to messages beyond 0 and -1 unsupported"
                         "- use DLTFile.lifecycles")
            raise IndexError()

    def clear_msgs(self):
        """Clear the first and last msg"""
        self._first_msg = None
        self._last_msg = None

    def get_end(self):
        """Get last msg in this lifecycle
        explicitly needed for old dlt-atlas scripts
        """
        return self._last_msg


@contextmanager
def handle_plugin_exceptions(plugin, action="running"):
    """Catch all exceptions and store them in the plugin.__exceptions structure"""
    start_time = time.time()
    try:
        yield
    except:  # pylint: disable=bare-except
        message = "Error {} plugin {} - {}".format(action, plugin.get_plugin_name(), sys.exc_info()[0])
        logger.error(message)
        logger.error(traceback.format_exc())
        if not isinstance(plugin, type):
            plugin.add_exception('\n'.join([message, traceback.format_exc()]))
    if not isinstance(plugin, type):
        plugin.add_timing(action, time.time() - start_time)


def _scan_folder(root, plugin_classes):
    """ Scans a folder seeking for plugins.

    Args:
        root(str): the path to scan.
        plugin_classes(list): a list which collects all plugins found.
    """
    if not os.path.isdir(root):  # Skip non-existing folders.
        logger.warn("Directory '%s' doesn't exist!", root)
        return

    filenames = os.listdir(root)
    if "__NO_PLUGINS__" in filenames:  # If the folder hasn't plugins, we skip it.
        return

    sys.path.insert(0, root)
    sys.path.insert(1, os.path.dirname(__file__))
    for name in filenames:
        full_path = os.path.join(root, name)
        if os.path.isdir(full_path):
            if name != 'tests':  # We skip the tests folder.
                _scan_folder(full_path, plugin_classes)
        elif name.endswith('.py') and not name.startswith('_'):  # We skip non-Python files, and private files.
            module_name = os.path.splitext(os.path.split(name)[-1])[0]
            try:
                __import__(module_name)

                module = sys.modules[module_name]
                for class_name in dir(module):
                    cls = getattr(module, class_name)
                    if six.PY3:
                        if (hasattr(cls, "__mro__") and issubclass(cls, Plugin) and
                                (not any(hasattr(getattr(cls, item), "__isabstractmethod__") and
                                         not isinstance(getattr(cls, item), property) for item in dir(cls)))):
                            plugin_classes.append(cls)
                    else:
                        if hasattr(cls, "__mro__") and issubclass(cls, Plugin) and not cls.__abstractmethods__:
                            plugin_classes.append(cls)
            except (ImportError, ValueError):
                logger.error("Could not load plugin %s\n%s", module_name, traceback.format_exc())


def get_plugin_classes(plugin_dirs):  # pylint: disable=too-many-locals
    """Collect plugin classes"""

    plugin_classes = []

    for plugins_dir in plugin_dirs:
        logger.info("Searching directory '%s' for plugins", plugins_dir)
        _scan_folder(plugins_dir, plugin_classes)

    return plugin_classes


class DLTAnalyser(object):
    """DLT Analyser"""

    def __init__(self):
        self.plugins = []
        self.file_exceptions = {}
        self.traces = []
        self._buffered_traces = []
        self.dlt_file = None

    def process_buffer(self):
        """Return buffered traces and clear buffer"""
        if self._buffered_traces:
            for trace in self._buffered_traces:
                self.process_message(trace)
            self._buffered_traces = []

    def load_plugins(self, plugin_dirs, plugins=None, exclude=None, no_default_dir=False):
        """Load plugins from "plugins" directory"""
        if no_default_dir is False:
            plugin_dirs += DEFAULT_PLUGINS_DIRS
        plugin_classes = get_plugin_classes(plugin_dirs)
        if plugins:
            plugins = list(set(plugins))
        for cls in plugin_classes:
            if plugins is None:
                if cls.manually_executed and \
                        os.environ.get("DLTLYSE_ALL_INCLUDES_MANUAL", "false").lower() not in ('1', 'true', 'yes',):
                    continue
            else:
                if not cls.get_plugin_name() in plugins:
                    continue
                plugins.remove(cls.get_plugin_name())
            if exclude is not None and cls.get_plugin_name() in exclude:
                continue
            logger.info("Loading plugin '%s' from '%s'", cls.get_plugin_name(), cls.__module__)
            with handle_plugin_exceptions(cls, 'loading'):
                self.plugins.append(cls())
        if plugins:
            logger.error("Some plugins that were requested were not found: %s", plugins)
            raise RuntimeError("Error loading requested plugins: {}".format(", ".join(plugins)))

    def show_plugins(self):
        """Show available plugins"""
        text = "Available plugins:\n"
        for plugin in self.plugins:
            classname = plugin.get_plugin_name()
            try:
                plugindoc = plugin.__doc__.splitlines()[0]
            except AttributeError:
                plugindoc = plugin.__doc__

            text += " - {} ({})\n".format(classname, plugindoc)
        return text

    def get_filters(self):
        """Extract filtering information from plugins"""
        filters = []
        for plugin in self.plugins:
            if plugin.message_filters == "all":
                logger.debug("Speed optimization disabled: '%s' plugin requires all messages",
                             plugin.get_plugin_name())
                filters = None
                break
            for flt in plugin.message_filters:
                if flt not in filters:
                    filters.append(flt)

        return filters

    def start_lifecycle(self, ecu_id, lifecycle_id):
        """call DltAtlas plugin API - new_lifecycle"""
        for plugin in self.plugins:
            with handle_plugin_exceptions(plugin, "calling new_lifecycle"):
                plugin.new_lifecycle(ecu_id, lifecycle_id)

    def process_message(self, message):
        """Pass on the message to plugins that need it"""
        for plugin in self.plugins:
            if plugin.message_filters == "all" or \
                (message.apid, message.ctid) in plugin.message_filters or \
                ("", message.ctid) in plugin.message_filters or \
                    (message.apid, "") in plugin.message_filters:
                with handle_plugin_exceptions(plugin, "calling"):
                    plugin(message)

    def end_lifecycle(self, lifecycle, lifecycle_id):
        """Finish lifecycle processing for all plugins"""
        for plugin in self.plugins:
            if hasattr(plugin, "prep_plugin_env"):
                plugin.prep_plugin_env(lifecycle, lifecycle_id)

        for plugin in self.plugins:
            with handle_plugin_exceptions(plugin, "calling end_lifecycle"):
                plugin.end_lifecycle(lifecycle.ecu_id, lifecycle_id)

    # pylint: disable=too-many-locals, too-many-statements
    def run_analyse(self, traces, xunit, no_sort, is_live, testsuite_name="dltlyse"):
        """Read the DLT trace and call each plugin for each message read"""
        filters = self.get_filters()
        # add filter for lifecycle start message in case it is missing
        # filters == None means no filtering is done at all
        flt = (DLT_LIFECYCLE_START["apid"].encode("utf-8"), DLT_LIFECYCLE_START["ctid"].encode("utf-8"))
        if filters and flt not in filters:
            filters.append(flt)

        old_lifecycle = None
        lifecycle = None
        last_msg = None
        lifecycle_id = 0
        self.traces = traces

        if is_live:
            signal.signal(signal.SIGINT, self.stop_signal_handler)

        for filename in traces:
            logger.info("Reading trace file '%s'", filename)
            with self.handle_file_exceptions(filename):
                tracefile = dlt.load(filename, split=not no_sort, filters=filters, live_run=is_live)
                self.dlt_file = tracefile
                msg = None
                for msg in tracefile:
                    is_start_msg = msg.compare(DLT_LIFECYCLE_START)
                    bufferable_msg = any(msg.compare(trace) for trace in buffer_matches)

                    # Buffer Messages if we find special
                    # marked msgs that should be buffered
                    # don't process these messages yet in this lifecycle
                    if bufferable_msg and len(self._buffered_traces) < MAX_BUFFER_SIZE:
                        self._buffered_traces.append(msg)
                        continue

                    # We found a start message, if this is the first ever then just start a new lifecycle,
                    # process any buffered messages and proceed. If we already have a lifecycle, then end that
                    # lifecycle and proceed as previously stated.
                    if is_start_msg:
                        if lifecycle:
                            lifecycle.set_last_msg(last_msg)
                            self.end_lifecycle(lifecycle, lifecycle.lifecycle_id)
                        lifecycle_id += 1
                        lifecycle = self.setup_lifecycle(msg=msg, lifecycle_id=lifecycle_id)
                        logger.info("DLT Analysis Starting life cycle %d", lifecycle.lifecycle_id)

                    if not lifecycle:
                        lifecycle = self.setup_lifecycle(msg, lifecycle_id=lifecycle_id, process_buffer=True)

                    self.process_buffer()
                    self.process_message(msg)
                    last_msg = msg

                if lifecycle:
                    lifecycle.set_last_msg(last_msg)
                    old_lifecycle = lifecycle

        # If the files only contained bufferable traces less than MAX_BUFFER_SIZE
        # we create a life_cycle 0 to accommodate these msgs
        if not lifecycle and self._buffered_traces:
            lifecycle = self.setup_lifecycle(msg=msg, lifecycle_id=lifecycle_id, process_buffer=True)
            old_lifecycle = lifecycle

        if old_lifecycle:
            self.process_buffer()
            self.end_lifecycle(old_lifecycle, lifecycle_id)

        return self.generate_reports(xunit, testsuite_name)

    def generate_reports(self, xunit, testsuite_name):
        """Generates reports at the end of execution"""
        logger.info("Generating reports")
        xreport = XUnitReport(outfile=xunit, testsuite_name=testsuite_name)
        run_result = 0
        file_results = []

        for plugin in self.plugins:
            output = "Report for {} ... ".format(plugin.get_plugin_name())
            with handle_plugin_exceptions(plugin, "calling report"):
                plugin.report()
            run_result |= 0 if plugin.report_exceptions() else 2
            for state in ["success", "error", "failure", "skipped"]:
                output += "{} {} ".format(len([x for x in plugin.get_results() if x.state == state]), state)
            if all([x.state in ["success", "skipped"] for x in plugin.get_results()]):
                output += "= passed."
            else:
                output += "= failed."
                run_result |= 1
                stdoutlogger.debug("- Error report for %s:", plugin.get_plugin_name())
                for result in plugin.get_results():
                    if result.state != "success":
                        stdoutlogger.debug(result.message)
                        stdoutlogger.debug(result.stdout)
            stdoutlogger.info(output)
            xreport.add_results(plugin.get_results())

        for filename in self.traces:
            output = "Report for file"
            if filename in self.file_exceptions:
                stdoutlogger.debug(self.file_exceptions[filename])
                stdoutlogger.info("%s %s ... = failed", output, filename)
                file_results.append(Result(
                    classname="DLTAnalyser",
                    testname="File Sanity Checks During Execution",
                    state="error",
                    stdout=self.file_exceptions[filename],
                    message=self.file_exceptions[filename]
                ))
            else:
                stdoutlogger.info("%s %s ... = passed", output, filename)
                file_results.append(Result(
                    classname="DLTAnalyser",
                    testname="File Sanity Checks During Execution",
                    state="success",
                    stdout="File Parsed Successfully",
                    message="File Parsed Successfully"
                ))

        xreport.add_results(file_results)

        if self.file_exceptions:
            run_result |= 4

        xreport.render()
        logger.info("Done.")
        return run_result

    def setup_lifecycle(self, msg, lifecycle_id, process_buffer=False):
        """Setup a new lifecycle by setting correct properties"""
        lifecycle = DLTLifecycle(ecu_id=msg.ecuid, lifecycle_id=lifecycle_id)
        lifecycle.set_first_msg(msg)
        self.start_lifecycle(lifecycle.ecu_id, lifecycle.lifecycle_id)
        if process_buffer:
            self.process_buffer()

        return lifecycle

    @contextmanager
    def handle_file_exceptions(self, file_name):
        """Catch all exceptions and store them in the DLTAnalyzer.file_exceptions structure"""
        try:
            yield
        except IOError as err:  # pylint: disable=bare-except
            message = "Error Loading File {} - {}".format(file_name, err)
            logger.exception(message)
            self.file_exceptions[file_name] = message

    def stop_signal_handler(self, signum, frame):
        """Catch SIGINT to stop any further analyzing of DLT Trace file in a live run"""
        logging.debug("Signal Handler called with signal:%d", signum)
        self.dlt_file.stop_reading.set()
