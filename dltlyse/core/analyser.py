"""DLT file analyser"""

from __future__ import print_function

from contextlib import contextmanager
from collections import defaultdict
import itertools
import logging
import os
import signal
import sys
import time
import traceback
from typing import DefaultDict, Dict, Iterable, List, Tuple, TypeVar

from dlt import dlt

from dltlyse.core.report import XUnitReport, Result
from dltlyse.core.plugin_base import Plugin

# pylint: disable= too-many-nested-blocks, no-member

T = TypeVar("T")

logger = logging.getLogger(__name__)
stdoutlogger = logging.getLogger("summary")
stdoutlogger.addHandler(logging.StreamHandler(sys.stdout))

DEFAULT_PLUGINS_DIRS = [
    os.path.join(os.path.dirname(__file__), "../plugins"),  # installation folder
    # e.g. /usr/bin/pythonX.X/site-packages/dltlyse/plugins
    os.path.join(os.getcwd(), "plugins"),  # plugins folder in current working directory
]

# Traces to buffer since they might be stored before lifecycle start message
BUFFER_MATCHES_MSG = {"apid": "DA1", "ctid": "DC1", "payload_decoded": "[connection_info ok] connected \00\00\00\00"}
BUFFER_MATCHES_ECUID = "XORA"
DLT_LIFECYCLE_START = {
    "apid": "DLTD",
    "ctid": "INTM",
    "payload_decoded": "Daemon launched. Starting to output traces...",
}
MAX_BUFFER_SIZE = 50


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
            logger.error("Access to messages beyond 0 and -1 unsupported" "- use DLTFile.lifecycles")
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


def make_plugin_exception_message(plugin, action, traceback_format_exc, sys_exec_info):
    """Handle plugin exception"""
    message = "Error {} plugin {} - {}".format(action, plugin.get_plugin_name(), sys_exec_info[0])
    logger.error(message)
    logger.error(traceback_format_exc)
    if not isinstance(plugin, type):
        plugin.add_exception("\n".join([message, traceback_format_exc]))


@contextmanager
def handle_plugin_exceptions(plugin, action="running"):
    """Catch all exceptions and store them in the plugin.__exceptions structure"""
    start_time = time.time()
    try:
        yield
    except:  # noqa: E722
        make_plugin_exception_message(plugin, action, traceback.format_exc(), sys.exc_info())

    if not isinstance(plugin, type):
        plugin.add_timing(action, time.time() - start_time)


def _scan_folder(root, plugin_classes):
    """Scans a folder seeking for plugins.

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
            if name != "tests":  # We skip the tests folder.
                _scan_folder(full_path, plugin_classes)
        elif name.endswith(".py") and not name.startswith("_"):  # We skip non-Python files, and private files.
            module_name = os.path.splitext(os.path.split(name)[-1])[0]
            try:
                __import__(module_name)

                module = sys.modules[module_name]
                for class_name in dir(module):
                    cls = getattr(module, class_name)
                    if (
                        hasattr(cls, "__mro__")
                        and issubclass(cls, Plugin)
                        and (
                            not any(
                                hasattr(getattr(cls, item), "__isabstractmethod__")
                                and not isinstance(getattr(cls, item), property)
                                for item in dir(cls)
                            )
                        )
                    ):
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


class DltlysePluginCollector(object):
    """Dispatch the dlt messages to each plugins

    The class collects all plugins by plugin's message filter setting. The
    analyser could pass messages to these plugins with fewer comparisons than
    before.

    Based on the performance consideration, these plugins are saved as a tuple.
    Since these data strcutre will be searched over million of times, choosing
    a low overhead data structure is necessary.
    """

    def __init__(self):  # type: () -> None
        self.msg_plugins = {}  # type: Dict[Tuple[str, str], Tuple[Plugin, ...]]
        self.apid_plugins = {}  # type: Dict[str, Tuple[Plugin, ...]]
        self.ctid_plugins = {}  # type: Dict[str, Tuple[Plugin, ...]]
        self.greedy_plugins = ()  # type: Tuple[Plugin, ...]

    def _convert_dict_value_tuple(self, plugins):  # type: (Dict[T, List[Plugin]]) -> Dict[T, Tuple[Plugin, ...]]
        """Helper function to convert the list value type to tuple value type"""
        return {key: tuple(value) for key, value in plugins.items() if value}

    def _dispatch_plugins(self, plugins):  # type: (Iterable[Plugin]) -> None
        """Dispatch plugins by message filters"""
        msg_plugins = defaultdict(list)  # type: DefaultDict[Tuple[str, str], List[Plugin]]
        apid_plugins = defaultdict(list)  # type: DefaultDict[str, List[Plugin]]
        ctid_plugins = defaultdict(list)  # type: DefaultDict[str, List[Plugin]]
        greedy_plugins = []  # type: List[Plugin]

        for plugin in plugins:
            msg_filters = plugin.message_filters
            if isinstance(msg_filters, str) and msg_filters == "all":
                greedy_plugins.append(plugin)
            elif isinstance(msg_filters, list):
                msg_filters = frozenset(msg_filters)  # type: ignore
                for apid, ctid in msg_filters:
                    if apid and ctid:
                        msg_plugins[apid, ctid].append(plugin)
                    elif apid:
                        apid_plugins[apid].append(plugin)
                    elif ctid:
                        ctid_plugins[ctid].append(plugin)

        self.msg_plugins = self._convert_dict_value_tuple(msg_plugins)
        self.apid_plugins = self._convert_dict_value_tuple(apid_plugins)
        self.ctid_plugins = self._convert_dict_value_tuple(ctid_plugins)
        self.greedy_plugins = tuple(greedy_plugins)

    def _check_plugin_msg_filters(self, plugins):  # type: (Iterable[Plugin]) -> None
        """Check the plugin's message filter setting

        Check if the message filters is valid. If there is any duplicated setting,
        it will cause the plugin to process the same message many times.

        :raises ValueError: When the settings of the plugin's message filter
                            is invalid.
        """
        for plugin in plugins:
            error_msg_postfix = "{plugin} - {msg_filters}".format(
                plugin=plugin.get_plugin_name(), msg_filters=plugin.message_filters
            )

            msg_filters = plugin.message_filters
            if isinstance(msg_filters, str):
                if msg_filters != "all":
                    raise ValueError("Invalid message filter setting: " + error_msg_postfix)
                continue

            if not msg_filters:
                raise ValueError("Message filter should not empty: " + error_msg_postfix)

            msg_filters = frozenset(plugin.message_filters)  # type: ignore
            apid_filters = {apid for apid, ctid in msg_filters if apid and not ctid}
            ctid_filters = {ctid for apid, ctid in msg_filters if not apid and ctid}

            if any(apid in apid_filters or ctid in ctid_filters for apid, ctid in msg_filters if apid and ctid):
                raise ValueError("Duplicated message filter setting: " + error_msg_postfix)

    def _convert_plugin_obj_to_name(self, plugins):  # (Union[Tuple[Plugin, ...], Dict[T, Tuple[Plugin, ...]]]) ->
        #   Union[List[str], Dict[_t, List[str]]]
        """Helper functioon to convert the plugin object to its name from a dict or a tuple

        The method is only used for debugging purpose.
        """
        if isinstance(plugins, tuple):
            return [plugin.get_plugin_name() for plugin in plugins]

        return {key: [plugin.get_plugin_name() for plugin in value] for key, value in plugins.items()}

    def _print_plugin_collections(self):  # type: () -> None
        """Print the collections for all plugins

        The method is only used for debugging purpose.
        """
        logger.debug("Message filter plugins: %s", self._convert_plugin_obj_to_name(self.msg_plugins))
        logger.debug("APID plugins: %s", self._convert_plugin_obj_to_name(self.apid_plugins))
        logger.debug("CTID plugins: %s", self._convert_plugin_obj_to_name(self.ctid_plugins))
        logger.debug("Greedy plugins: %s", self._convert_plugin_obj_to_name(self.greedy_plugins))

    def init_plugins(self, plugins):  # type: (List[Plugin]) -> None
        """Init with plugins

        Please call the function after all plugins are initialized, the method
        parses the plugin's message filter then creates the
        corresponding plugin lists for message dispatching.
        """
        self._check_plugin_msg_filters(plugins)
        self._dispatch_plugins(plugins)
        self._print_plugin_collections()


class DLTAnalyser(object):
    """Main program to run live/offline analysis

    The analyser receives/get dlt messages. If the message is a lifecycle-start message,
    the analyser will end last life cycle, start a new lifecycle and pass the
    information to plugins which are implemented with `new_lifecycle` and `end_lifecycle`.
    If the message is a normal message. The message will be passed to registered plugins.

    The class is not a plugin. If there is an uncaught exception happened in
    execution time, the File Sanity Check will fail.
    """

    def __init__(self):
        self.plugins = []
        self.file_exceptions = {}
        self.traces = []
        self._buffered_traces = []
        self.dlt_file = None
        self.plugin_collector = DltlysePluginCollector()

    def process_buffer(self):
        """Return buffered traces and clear buffer"""
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
                if cls.manually_executed and os.environ.get("DLTLYSE_ALL_INCLUDES_MANUAL", "false").lower() not in (
                    "1",
                    "true",
                    "yes",
                ):
                    continue
            else:
                if not cls.get_plugin_name() in plugins:
                    continue
                plugins.remove(cls.get_plugin_name())
            if exclude is not None and cls.get_plugin_name() in exclude:
                continue
            logger.info("Loading plugin '%s' from '%s'", cls.get_plugin_name(), cls.__module__)
            with handle_plugin_exceptions(cls, "loading"):
                self.plugins.append(cls())
        if plugins:
            logger.error("Some plugins that were requested were not found: %s", plugins)
            raise RuntimeError("Error loading requested plugins: {}".format(", ".join(plugins)))

        self.plugin_collector.init_plugins(self.plugins)

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
        filters = set()
        for plugin in self.plugins:
            if plugin.message_filters == "all":
                logger.debug(
                    "Speed optimization disabled: '%s' plugin requires all messages", plugin.get_plugin_name()
                )
                return None
            for flt in plugin.message_filters:
                filters.add(flt)

        return list(filters)

    def start_lifecycle(self, ecu_id, lifecycle_id):
        """call DltAtlas plugin API - new_lifecycle"""
        for plugin in self.plugins:
            with handle_plugin_exceptions(plugin, "calling new_lifecycle"):
                plugin.new_lifecycle(ecu_id, lifecycle_id)

    def end_lifecycle(self, lifecycle, lifecycle_id):
        """Finish lifecycle processing for all plugins"""
        for plugin in self.plugins:
            if hasattr(plugin, "prep_plugin_env"):
                plugin.prep_plugin_env(lifecycle, lifecycle_id)

        for plugin in self.plugins:
            with handle_plugin_exceptions(plugin, "calling end_lifecycle"):
                plugin.end_lifecycle(lifecycle.ecu_id, lifecycle_id)

    def process_message(self, msg):
        """Process the message"""
        msg_apid = msg.apid
        msg_ctid = msg.ctid

        for plugin in itertools.chain(
            self.plugin_collector.msg_plugins.get((msg_apid, msg_ctid), ()),
            self.plugin_collector.apid_plugins.get(msg_apid, ()),
            self.plugin_collector.ctid_plugins.get(msg_ctid, ()),
            self.plugin_collector.greedy_plugins,
        ):
            try:
                plugin(msg)
            except:  # noqa: E722
                make_plugin_exception_message(plugin, "calling", traceback.format_exc(), sys.exc_info())

    # pylint: disable=too-many-locals, too-many-statements
    def run_analyse(self, traces, xunit, no_sort, is_live, testsuite_name="dltlyse"):
        """Read the DLT trace and call each plugin for each message read"""
        #
        # CAUTION: DON'T REFACTOR THE METHOD FOR READABILITY.
        #
        # The method is optimized for performance. We do a lot of optimizations
        # for the method (e.g. avoid to access attribute with dots, function
        # inlining, loop unrolling, ...).  The inner most loop is called over
        # 10 million times when the input file is large. Any small/tiny change
        # could causes performance pentlty.

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

        # Optimization: Local variables for global constant values
        # https://wiki.python.org/moin/PythonSpeed/PerformanceTips#Local_Variables
        buffer_matches_msg_apid = BUFFER_MATCHES_MSG["apid"]
        buffer_matches_msg_ctid = BUFFER_MATCHES_MSG["ctid"]
        buffer_matches_msg_payload_decoded = BUFFER_MATCHES_MSG["payload_decoded"]  # pylint: disable=invalid-name
        dlt_lifecycle_start_apid = DLT_LIFECYCLE_START["apid"]
        dlt_lifecycle_start_ctid = DLT_LIFECYCLE_START["ctid"]
        dlt_lifecycle_start_payload_decoded = DLT_LIFECYCLE_START["payload_decoded"]  # pylint: disable=invalid-name

        # Optimization: Local variables for the get functions
        # ref: https://wiki.python.org/moin/PythonSpeed/PerformanceTips#Avoiding_dots...
        msg_plugins_getter = self.plugin_collector.msg_plugins.get
        apid_plugins_getter = self.plugin_collector.apid_plugins.get
        ctid_plugins_getter = self.plugin_collector.ctid_plugins.get
        greedy_plugins = self.plugin_collector.greedy_plugins

        for filename in traces:
            logger.info("Reading trace file '%s'", filename)
            with self.handle_file_exceptions(filename):
                tracefile = dlt.load(filename, split=not no_sort, filters=filters, live_run=is_live)
                self.dlt_file = tracefile
                msg = None
                for msg in tracefile:
                    # Optimization: Local variables for values
                    # https://wiki.python.org/moin/PythonSpeed/PerformanceTips#Local_Variables
                    msg_apid = msg.apid
                    msg_ctid = msg.ctid
                    msg_payload_decoded = msg.payload_decoded

                    # Buffer Messages if we find special
                    # marked msgs that should be buffered
                    # don't process these messages yet in this lifecycle
                    #
                    # Optimization: don't use msg.compare here, just expand
                    # the comparison to reduce any unnecessary comparisons
                    if (
                        (
                            msg_apid == buffer_matches_msg_apid
                            and msg_ctid == buffer_matches_msg_ctid
                            and msg_payload_decoded == buffer_matches_msg_payload_decoded
                        )
                        or msg.ecuid == BUFFER_MATCHES_ECUID
                    ) and len(self._buffered_traces) < MAX_BUFFER_SIZE:
                        self._buffered_traces.append(msg)
                        continue

                    # We found a start message, if this is the first ever then just start a new lifecycle,
                    # process any buffered messages and proceed. If we already have a lifecycle, then end that
                    # lifecycle and proceed as previously stated.
                    #
                    # Optimization: don't use msg.compare here, just expand
                    # the comparison to reduce any unnecessary comparisons
                    if (
                        msg_apid == dlt_lifecycle_start_apid
                        and msg_ctid == dlt_lifecycle_start_ctid
                        and msg_payload_decoded == dlt_lifecycle_start_payload_decoded
                    ):
                        if lifecycle:
                            lifecycle.set_last_msg(last_msg)
                            self.end_lifecycle(lifecycle, lifecycle.lifecycle_id)
                        lifecycle_id += 1
                        lifecycle = self.setup_lifecycle(msg=msg, lifecycle_id=lifecycle_id)
                        logger.info("DLT Analysis Starting life cycle %d", lifecycle.lifecycle_id)

                    if not lifecycle:
                        lifecycle = self.setup_lifecycle(msg, lifecycle_id=lifecycle_id, process_buffer=True)

                    if self._buffered_traces:
                        self.process_buffer()

                    # Optimization:
                    # 1. Inline the self.process_message function, it could
                    #    reduce at 5 byte-code instructions and we could use
                    #    local variables to reduce the access time for plugin
                    #    lists.
                    # 2. loop unrolling for these plugin lists. Without
                    #    performance consideration, we could use itertool.chains
                    #    to reduce the bolierplate code. But it is slower 3x
                    #    than the unrolling version.
                    # 3. Inline the exception handing rather than use a context
                    #    manager. It reduces at least 10 byte-code instructions.
                    # 4. Remove the recording the execution time for each plugin
                    #    It could speed up more than 5% execution time. If you
                    #    have need to know the execution time for each plugin,
                    #    you could replace the try-except block with
                    #    `handle_plugin_exceptions` to get it.
                    # 5. Return a empty tuple when the plugin list is not found,
                    #    a tuple is a singleton object, it avoids any unnecessary
                    #    object constructions/destructions.
                    for plugin in msg_plugins_getter((msg_apid, msg_ctid), ()):
                        try:
                            plugin(msg)
                        except:  # noqa: E722
                            make_plugin_exception_message(plugin, "calling", traceback.format_exc(), sys.exc_info())
                    for plugin in apid_plugins_getter(msg_apid, ()):
                        try:
                            plugin(msg)
                        except:  # noqa: E722
                            make_plugin_exception_message(plugin, "calling", traceback.format_exc(), sys.exc_info())
                    for plugin in ctid_plugins_getter(msg_ctid, ()):
                        try:
                            plugin(msg)
                        except:  # noqa: E722
                            make_plugin_exception_message(plugin, "calling", traceback.format_exc(), sys.exc_info())
                    for plugin in greedy_plugins:
                        try:
                            plugin(msg)
                        except:  # noqa: E722
                            make_plugin_exception_message(plugin, "calling", traceback.format_exc(), sys.exc_info())

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
                file_results.append(
                    Result(
                        classname="DLTAnalyser",
                        testname="File Sanity Checks During Execution",
                        state="error",
                        stdout=self.file_exceptions[filename],
                        message=self.file_exceptions[filename],
                    )
                )
            else:
                stdoutlogger.info("%s %s ... = passed", output, filename)
                file_results.append(
                    Result(
                        classname="DLTAnalyser",
                        testname="File Sanity Checks During Execution",
                        state="success",
                        stdout="File Parsed Successfully",
                        message="File Parsed Successfully",
                    )
                )

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
