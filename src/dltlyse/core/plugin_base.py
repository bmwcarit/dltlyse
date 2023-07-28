# Copyright (C) 2022. BMW Car IT GmbH. All rights reserved.
"""Base class for dltlyse plugins"""

import copy
import csv
import functools
import inspect
import logging
import os
import re
from typing import List, Optional, Tuple

from abc import ABCMeta, abstractmethod
from collections import defaultdict

from dltlyse.core.report import Result
from dltlyse.core.utils import round_float

# pylint: disable= unsupported-membership-test

EXTRACT_DIR = "extracted_files"
logger = logging.getLogger(__name__)


def plugin_metadata(**kwargs):
    """Plugin metadata decorator for Plugin class

    You can add metadata information in your Plugin class. For example,

        @plugin_metadata(type="test", function="monitor")
        class TestMetadataPlugin(Plugin):
            pass

    The metadata is stored in cls.plugin_metadata

        >>> print(TestMetadataPlugin.plugin_metadata)
        {'type': 'test', 'function': 'monitor'}

    If the class is derived from another Plugin with metadata, the class also has the metadata of parent class. If the
    parent and derived class have the same key, the value will be from derived class. For example,

        @plugin_metadata(function="logging", extra="extra")
        class TestMetadataLoggingPlugin(Plugin):
            pass

        >>> print(TestMetadataPlugin.plugin_metadata)
        {"type": "test", "function": "logging", "extra": "extra"}

    You can get the complete example from dltlyse/core/tests/test_plugin_report.py

    The current usage is that the dltlyse xunit report will show metadata for each plugin.
    """

    def _metadata(cls):  # pylint: disable=missing-docstring
        metadata_key = "plugin_metadata"
        metadata = copy.deepcopy(getattr(cls, metadata_key, {}))
        metadata.update(kwargs)

        setattr(cls, metadata_key, metadata)

        return cls

    return _metadata


class Plugin(object):
    """dltlyse Plugin base class"""

    __metaclass__ = ABCMeta

    # message filters are filters that will be used during loading DLT trace file. Each plugin defines
    # list of (APID, CTID) pairs and only messages matching those criteria are read from the DLT trace file.
    # This is used for speed optimization
    # Limitation: DLT library only supports adding 30 filters. If we collect more than 30 filter pairs, the whole
    #     mechanism is disabled
    # For special purposes when you need to analyse all messages, you can define message_filters = "all"
    # which also disables the filtering completely.
    message_filters: List[Optional[Tuple[str, str]]] = []

    manually_executed = False  # True if a plugin should be manually selected (not automatic execution).

    def __init__(self):
        self.__results = []
        self.__exceptions = []
        self.__timings = defaultdict(float)

    @abstractmethod
    def __call__(self, message):
        """object will be called for every message

        param: DltMessage message: object represeting a single line in DLT log. Commonly used methods are:
            message.compare(dict(apid="APP", ctid="CONTEXT")) -- match a message to a filter
            str(message.payload_decoded) - full payload of the message as a string
            message.payload - a list with payload data fields with their types
            message.tmsp - message timestamp (relative to lifecycle start)
        """
        pass

    @classmethod
    def get_plugin_name(cls):
        """Return plugin name"""
        return cls.__name__

    @abstractmethod
    def report(self):
        """Report the run after all messages has been read"""
        pass

    def add_result(self, **kwargs):
        """Adds a Result object with set values

        :param str state: possible values "success", "error", "failures", "skipped"
        :param str message: log for the result
        :param str stdout: stdout
        :param str stderr: stderr
        """
        # Parse class name
        kwargs.setdefault("classname", self.get_plugin_name())

        # Parse class docstring
        plugin_docstring = inspect.getdoc(self)

        # Parse plugin short description
        kwargs.setdefault("testname", plugin_docstring.splitlines()[0] if plugin_docstring else type(self).__name__)

        # Parse plugin metadata and add plugin docstring
        metadata = copy.deepcopy(getattr(self, "plugin_metadata", {}))
        metadata["docstring"] = plugin_docstring or ""
        kwargs.setdefault("metadata", metadata)

        self.__results.append(Result(**kwargs))

    def add_attachments(self, attachments):
        """Adds attachments to the last result, creating a result if none exist"""
        if not self.__results:
            self.add_result()
        if attachments:
            self.__results[-1].attach.extend(attachments)

    def add_timing(self, action, timing):
        """Add time used by the plugin in an action"""
        self.__timings[action] += timing

    def add_exception(self, message):
        """Add an exception message"""
        if message not in self.__exceptions:
            self.__exceptions.append(message)

    def report_exceptions(self):
        """Report all detected exceptions"""
        logger.debug(
            "Timings of plugin %s: %s",
            self.get_plugin_name(),
            {k: str(round_float(v, 2)) for k, v in self.__timings.items()},
        )
        if self.__exceptions:
            self.add_result(
                testname="Exceptions during execution",
                state="error",
                message="Exceptions detected while executing the plugin",
                stdout="\n-------------\n".join(self.__exceptions),
            )
            return False
        return True

    def get_results(self):
        """Return the results object"""
        return self.__results

    def new_lifecycle(self, ecu_id, lifecycle_id):  # pylint: disable=no-self-use,unused-argument
        """Called at the start of each lifecycle (including first)"""
        pass

    def end_lifecycle(self, ecu_id, lifecycle_id):  # pylint: disable=no-self-use,unused-argument
        """Called at the end of each lifecycle (including last)"""
        pass


class CSVPlugin(Plugin):  # pylint: disable=abstract-method
    """Base class for plugins that output a CSV file as an output"""

    # If you have only one file you can use these two lines
    csv_filename = None  # If you only have one file, you can use this. Set to "subdir/example.csv" in subclass
    csv_fields = None  # If using only one file, set this to the list of column headers

    # If you want to use multiple CSV files, please use csv_filenames and provide columns per file
    csv_filenames = None
    # Examples:
    # csv_filenames = {}
    # csv_filenames ["my_csvfile.csv"] = ["column1", "column2", ...]
    # csv_filenames ["my_subdir/my_csvfile2.csv"] = ["column2.1", "column2.2", ...]

    def __init__(self):
        self._csv = {}
        self._csv_fileobj = {}
        # for backward compatibility: if csv_filename was defined, add it to csv_filenames
        if self.csv_filename:
            self.csv_filenames = {self.csv_filename: self.csv_fields}
        super(CSVPlugin, self).__init__()

    def _create_csvfile(self, filename=None):
        """Create csv file and add first row with column names"""
        filename = filename or list(self.csv_filenames)[0]
        pathname = os.path.join(EXTRACT_DIR, filename)
        if not os.path.exists(os.path.dirname(pathname)):
            os.makedirs(os.path.dirname(pathname))

        self._csv_fileobj[filename] = open(pathname, "w")
        self._csv[filename] = csv.writer(self._csv_fileobj[filename])
        if self.csv_filenames[filename]:  # Only write header line if columns are defined.
            self._csv[filename].writerow(self.csv_filenames[filename])
        else:
            logger.debug("No header line written to file %s", filename)

    def writerow(self, data_row, filename=None):
        """Write a row to CSV file"""
        filename = filename or list(self.csv_filenames)[0]
        if filename not in self._csv:
            self._create_csvfile(filename)
        self._csv[filename].writerow(data_row)

    def writerows(self, data_rows, filename=None):
        """Write several rows to csv file"""
        filename = filename or list(self.csv_filenames)[0]
        if filename not in self._csv:
            self._create_csvfile(filename)
        self._csv[filename].writerows(data_rows)

    def report(self):
        """Write the csv file"""
        self._close_csv_files()
        self.add_attachments(self.csv_filenames.keys())

    def _close_csv_file(self, filename=None):
        """Close CSV file"""
        filename = filename or list(self.csv_filenames)[0]
        if self._csv[filename]:
            self._csv_fileobj[filename].close()

    def _close_csv_files(self):
        """Close all CSV files"""
        for filename in self._csv:
            self._close_csv_file(filename)


class LifecycleCSVPlugin(CSVPlugin):  # pylint: disable=abstract-method
    """Used to create a set of csv files for every lifecycle"""

    # These will be copied to csv_filenames and csv_fields for every lifecycle
    lifecycle_csv_filenames = None

    __all_csv_filenames = None

    def new_lifecycle(self, ecu_id, lifecycle_id):
        """Creates the CSV files for the lifecycle"""
        base_folder = "Lifecycles/{0:02}".format(lifecycle_id)
        self.csv_filenames = {os.path.join(base_folder, k): v for k, v in self.lifecycle_csv_filenames.items()}
        super(LifecycleCSVPlugin, self).new_lifecycle(ecu_id, lifecycle_id)

    def end_lifecycle(self, ecu_id, lifecycle_id):
        """Closes the CSV files and stores them for attaching to the result"""
        self._close_csv_files()
        if not self.__all_csv_filenames:
            self.__all_csv_filenames = []
        self.__all_csv_filenames.extend(self.csv_filenames.keys())
        super(LifecycleCSVPlugin, self).end_lifecycle(ecu_id, lifecycle_id)

    def report(self):
        """Attaches all CSV files to the result"""
        self.add_attachments(self.__all_csv_filenames)

    def find_file(self, filename):
        """Find a filename matching a substring from the current lifecycle"""
        return [afile for afile in self.csv_filenames.keys() if filename in afile][0]


def dlt_callback(app_id=None, ctx_id=None):
    """Decorates a method which is intended to be used as a callback for dltlyse.

    It collects the app_id and ctx_id values, and saves them into the method.

    Args:
        app_id(str): if defined, is the app_id that we want to catch.
        ctx_id(str): if defined, is the ctx_id that we want to catch.
    """

    def wrapper(func):  # pylint: disable=missing-docstring
        func.filter_condition = app_id or "", ctx_id or ""

        return func

    return wrapper


class CallBacksAndReportPlugin(Plugin):  # pylint: disable=abstract-method
    """An extended version of the dltlyse Plugin, which automatically handles some common operations.

    A get_report method is provided, which automatically gets the report_output member, converts it
    to a string and writes the result to a file with the class name (converting all capital letters
    to '_' + their lowercase) + .txt appended as filename.
    So, basically a plugin has just to collect its data and put them in the report_output member.
    get_report calls prepare_report before writing the report to the file, because sometimes a
    preparation is needed to generate the final report.

    This plugin provides also a facility for registering callbacks: it's enough to decorate them
    with dlt_callback, providing the app_id and/or ctx_id filters (see dlt_callback's docstring).
    All methods which are decorated will be automatically retrieved and registered.

    Example:
        @dlt_callback('LTM', 'MAIN')
        def gather_version_info(self, frame):
            pass

    The plugin then will take care of calling the registered callbacks only when the proper filter
    conditions are matched, so eventually they only have to look at the payload.

    Finally, it automatically sets the log level to DEBUG, and creates a logger using the class
    name. The logger is available as the logger member.
    """

    def __init__(self):
        """Automatically sets a default for report (None -> no report) and logger."""
        self.collect_and_register_callbacks()
        self.report_output = None  # Should be defined before calling the parent constructor.

        super(CallBacksAndReportPlugin, self).__init__()

        self.logger = logging.getLogger(self.get_plugin_name())

    def collect_and_register_callbacks(self):
        """Collects and registers all dlt callbacks.

        The dlt callbacks should be decorated with the dlt_callback decorator.
        It also registers all message filters in class.message_filters.
        """
        self.dlt_callbacks = defaultdict(list)
        self.dlt_greedy_callbacks = []
        for member_name in dir(self):  # Scans the class members.
            member = getattr(self, member_name)
            filter_condition = getattr(member, "filter_condition", None)
            if filter_condition:
                if filter_condition[0] or filter_condition[1]:
                    if self.message_filters != "all":
                        self.message_filters.append(filter_condition)  # pylint: disable=no-member
                    self.dlt_callbacks[filter_condition].append(member)
                else:
                    self.message_filters = "all"
                    self.dlt_greedy_callbacks.append(member)

    # pylint: disable=invalid-name
    def add_callback_from_template_function(self, template_function, app_id, ctx_id, userdata):
        """Adds an additional callback which is automatically generated from a "template" function or method.

        Args:
            template_function(function or method): a function or method that acts a template, to be "specialized"
            (according to the given app_id, ctx_id, payloads) to catch specific traces.
            app_id(str): the app id.
            ctx_id(str): the context id.
            userdata(object): normally is a sequence of strings that should be matched in the trace payload, but in
            reality it can be anything, since it's up to the template function to use this parameter as it wants.
        """
        # Data should be converted to strings, since dltlyse fails to register a filter if it's using unicode strings.
        app_id, ctx_id, userdata = (
            str(app_id),
            str(ctx_id),
            str(userdata) if isinstance(userdata, str) else userdata,
        )

        callback = functools.partial(template_function, app_id=app_id, ctx_id=ctx_id, userdata=userdata)
        callback = dlt_callback(app_id, ctx_id)(callback)
        filter_condition = app_id, ctx_id
        if filter_condition[0] or filter_condition[1]:
            if self.message_filters != "all":
                self.message_filters.append(filter_condition)  # pylint: disable=no-member
            self.dlt_callbacks[filter_condition].append(callback)
        else:
            self.message_filters = "all"
            self.dlt_greedy_callbacks.append(callback)

    def get_result_dir(self):
        """Return result directory"""
        if not os.path.exists(EXTRACT_DIR):
            os.makedirs(EXTRACT_DIR)

        return EXTRACT_DIR

    def report_filename(self):
        """Builds & returns a standard/base filename for the report."""
        # Converts all uppercase letters in lowercase, pre-pending them with a '_'.
        report_filename = re.sub(r"([A-Z])", r"_\1", self.get_plugin_name())

        return report_filename.lower().strip("_") + ".txt"

    def prepare_report(self):
        """It's invoked just before writing the report to file, in case that some operation needs
        to be done to prepare the report with the final/required format (a string, or a list/tuple/
        dict).
        """
        pass

    def get_report(self):
        """Provides automatic report generation.

        prepare_report is called to ensure that the report is ready for writing.
        Then the type of the report data is analyzed, to see if a JSON file (for list, tuple, or
        dict data type) should be written instead of the normal string/text file.
        """
        self.prepare_report()
        if self.report_output is None:
            return "No report is generated!"
        return self.write_to_domain_file(self.report_filename(), str(self.report_output))

    def write_to_domain_file(self, filename, report):
        """Write the given report to a file.

        Args:
            filename(str): the filename.
            report(str): the string with the report to be saved.
        """
        fullpath = os.path.join(self.get_result_dir(), filename)
        with open(fullpath, "w") as report_file:
            report_file.write(report)
        self.logger.info("See %s", fullpath)

        return fullpath

    def __call__(self, message):
        """Dispatches the message to the registered callback.

        The callbacks were registered with the dlt_callbacks decorator.
        """
        for callback in self.dlt_callbacks[message.apid, message.ctid]:  # pylint: disable=no-member
            callback(message)
        for callback in self.dlt_greedy_callbacks:  # pylint: disable=no-member
            callback(message)
