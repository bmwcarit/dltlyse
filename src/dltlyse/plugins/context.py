# Copyright (C) 2022. BMW Car IT GmbH. All rights reserved.
"""Count DLTD INTM DLT messages"""

from dltlyse.core.plugin_base import Plugin


class ContextPlugin(Plugin):
    """Count DLTD INTM messages"""

    message_filters = [("DLTD", "INTM")]

    matched_messages = 0

    def __call__(self, message):
        if message.apid == "DLTD" and message.ctid == "INTM":
            self.matched_messages += 1

    def report(self):
        if self.matched_messages > 0:
            self.add_result(stdout="found {} DLTD INTM messages".format(self.matched_messages))
        else:
            self.add_result(state="failure", message="could not find any DLTD INTM messages in the trace")
