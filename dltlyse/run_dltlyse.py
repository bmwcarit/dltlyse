#!/usr/bin/env python
"""DLT file analyser"""

from __future__ import print_function

try:
    import configparser
except ImportError:
    import ConfigParser as configparser
import argparse
import fnmatch
import logging
import os
import sys

from dltlyse.core.analyser import DLTAnalyser

# pylint: disable=dangerous-default-value

logger = logging.getLogger("dltlyse")


def parse_options(args=sys.argv[1:]):
    """parse command line parameters"""

    # Turn off help, so we print all options in response to -h
    conf_parser = argparse.ArgumentParser(add_help=False)
    conf_parser.add_argument("-c", "--config", dest="config_file", metavar="FILE", help="Use specific config file")

    args, remaining_args = conf_parser.parse_known_args(args)
    defaults = {"plugins": None}
    if args.config_file:
        if not os.path.exists(args.config_file):
            raise IOError("Configuration file '{}' could not be found.".format(args.config_file))
        config = configparser.ConfigParser()
        config.read([args.config_file])
        defaults = dict(config.items("default"))

    # https://gist.github.com/von/949337/
    # Don't surpress add_help here so it will handle -h
    parser = argparse.ArgumentParser(
        # Inherit options from config_parser
        parents=[conf_parser],
        # print script description with -h/--help
        description=__doc__,
        # Don't mess with format of description
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # convert string to list
    if isinstance(defaults["plugins"], str):
        defaults["plugins"] = defaults["plugins"].split(",")
    parser.set_defaults(**defaults)

    parser.add_argument(
        "-d",
        "--plugins-dir",
        dest="plugin_dirs",
        action="append",
        default=[],
        help="Add directory to search for plugins",
    )
    parser.add_argument(
        "--no-default-dir",
        dest="no_default_dir",
        action="store_true",
        default=False,
        help="Do not look for plugins in the default directories",
    )
    parser.add_argument(
        "-p",
        "--plugins",
        dest="plugins",
        action="append",
        default=defaults["plugins"],
        help="Initialize only explicitly listed plugin classes",
    )
    parser.add_argument("--exclude", dest="exclude", action="append", help="Exclude listed plugin classes")
    parser.add_argument(
        "-s", "--show-plugins", dest="show_plugins", action="store_true", default=False, help="Show available plugins"
    )
    parser.add_argument(
        "-r",
        "--recursive",
        dest="recursive_search",
        action="store_true",
        default=False,
        help="Search directories for traces recursively",
    )
    parser.add_argument(
        "-v", "--verbose", dest="verbose", action="store_true", default=False, help="Turn on verbose messages"
    )
    parser.add_argument(
        "-x",
        "--xunit",
        dest="xunit",
        default="dltlyse_results.xml",
        help="Generate result file in xUnit format to the specified file",
    )
    parser.add_argument(
        "--xunit-testsuite-name",
        dest="xunit_testsuite_name",
        default="dltlyse",
        help="Testsuite name used inside the xunit results file",
    )
    parser.add_argument(
        "--no-sort", dest="no_sort", action="store_true", default=False, help="Compatibility option - ignored"
    )
    parser.add_argument(
        "--live-run",
        dest="live_run",
        action="store_true",
        default=False,
        help="Do a live run of DLTlyse plugins on incoming DLT logs",
    )
    parser.add_argument("traces", nargs="*", help="DLT trace files")

    return parser.parse_args(remaining_args)


def main():
    """Entry point"""
    logging.basicConfig(level=logging.INFO)

    options = parse_options()

    logging.root.setLevel(logging.DEBUG if options.verbose is True else logging.INFO)

    if len(options.traces) > 1 and options.live_run:
        logger.error("DLTlyse does not support multiple trace files with '--live-run' option.")
        return 1

    analyser = DLTAnalyser()
    analyser.load_plugins(
        plugin_dirs=options.plugin_dirs,
        plugins=options.plugins,
        exclude=options.exclude,
        no_default_dir=options.no_default_dir,
    )
    if options.show_plugins:
        print(analyser.show_plugins(), file=sys.stderr)
        return 0

    traces = []
    for trace in options.traces:
        if os.path.isdir(trace):
            dir_traces = []
            if options.recursive_search is True:
                for root, _, filenames in os.walk(trace):
                    for filename in fnmatch.filter(filenames, "*.dlt"):
                        dir_traces.append(os.path.join(root, filename))
            else:
                for filename in fnmatch.filter(os.listdir(trace), "*.dlt"):
                    dir_traces.append(os.path.join(trace, filename))
            traces.extend(sorted(dir_traces))
        else:
            traces.append(trace)

    return analyser.run_analyse(
        traces,
        xunit=options.xunit,
        no_sort=True,
        is_live=options.live_run,
        testsuite_name=options.xunit_testsuite_name,
    )


if __name__ == "__main__":
    sys.exit(main())
