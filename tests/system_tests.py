"""Basic DLTlyse tests"""

import sys
from nose.tools import assert_greater, assert_in, assert_equal, assert_true

from mtee.testing.tools import assert_process_returncode, run_command
from mtee.tools.nose_parametrize import nose_parametrize

from dltlyse.core.utils import seconds_to_human_readable


class TestsDltlyse(object):
    """Test DLTlyse exections"""

    sdk_path = "/"
    command = [sys.executable, "./run-dltlyse"]

    def test_show_plugins(self):
        """Test DLTlyse show plugin execution"""
        cmd = self.command + ["-s"]
        result = run_command(cmd)
        assert_process_returncode(0, result, "dltlyse execution failed. Expected pass")
        assert_in("Available plugins", result.stderr)
        assert_greater(len(result.stderr.split("\n")), 1, "No plugins loaded")

    def test_no_traces(self):
        """Test DLTlyse run without traces"""
        cmd = self.command
        result = run_command(cmd)
        # TODO - re-enable once traffic load plugin is fixed
        # assert_process_returncode(0, result, "dltlyse execution without traces failed, expected a pass")
        assert_true(result)


@nose_parametrize(
    (0.01, "0:00:00.01"),
    (0.1, "0:00:00.10"),
    (0.25, "0:00:00.25"),
    (1, "0:00:01.00"),
    (1.25, "0:00:01.25"),
    (61, "0:01:01.00"),
    (61.2, "0:01:01.20"),
    (3600, "1:00:00.00"),
    (3661.25, "1:01:01.25"),
)
def test_seconds_to_human_readable(seconds, result):
    """Test conversion of seconds to human readable time string"""
    assert_equal(seconds_to_human_readable(seconds), result)
