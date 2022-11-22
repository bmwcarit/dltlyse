"""Search SYS|JOUR for detected errors"""

import collections
import re

from dltlyse.core.plugin_base import Plugin


class TestSysErrorPlugin(Plugin):
    """Errors found by SYS|JOUR"""

    # relevant APIDs and CTIDs to filter for
    #  - SYS|JOUR: error detection
    message_filters = [("SYS", "JOUR")]
    shared_regex = re.compile(
        r"\[[0-9]*\]: (?P<program>\S*?): error while loading shared libraries: "
        r"(?P<librabry>\S*?): cannot open shared object file"
    )

    errors = collections.defaultdict(set)

    def __call__(self, message):
        """Handle traces"""
        if not (message.apid == "SYS" and message.ctid == "JOUR"):
            return

        payload_decoded = str(message.payload_decoded)
        match = self.shared_regex.search(payload_decoded)
        if match:
            self.errors["error while loading shared libraries"].add(
                "{} faild to load {}".format(match.group("program"), match.group("librabry"))
            )

    def report(self):
        """Report if errors were found"""

        if self.errors:
            message = "\n".join(self.errors.keys())
            stdout = []
            for error in self.errors:
                stdout.append("{}:\n{}".format(error, "\n".join(self.errors[error])))
            self.add_result(state="failure", message=message, stdout="\n---\n".join(stdout))
        else:
            self.add_result(message="No errors found")
