# Copyright (C) 2016. BMW Car IT GmbH. All rights reserved.
"""Extracting all files from DLT trace

Example:

$ python dltlyse.py -p ExtractFilesPlugin vmwx86_full_trace.dlt
"""

from __future__ import print_function

import logging
import os

from collections import OrderedDict
from dltlyse.core.plugin_base import Plugin, EXTRACT_DIR

COREDUMP_DIR = "Coredumps"
FULL_EXTRACT_DIR = os.path.join(EXTRACT_DIR, COREDUMP_DIR)

logger = logging.getLogger(__name__)


class File(object):
    """File data"""
    def __init__(self, transfer_id, filename):
        self.transfer_id = transfer_id
        self.filename = filename
        self.index = 0
        self.error = False
        self.finished = False
        # store the temporary (part) file in the extracted_files/Coredumps/${transfer_id}/${filename}.part
        self._part_filepath = os.path.join(FULL_EXTRACT_DIR, self.transfer_id, self.filename + ".part")

        # warn if the file has been already extracted before (not finished extraction)
        if os.path.exists(self._part_filepath):
            logger.warning("File '%s' exists already!", self._part_filepath)
        # make sure the extracted_files/Coredumps/${transfer_id} directory exists
        if not os.path.exists(os.path.join(FULL_EXTRACT_DIR, self.transfer_id)):
            os.makedirs(os.path.join(FULL_EXTRACT_DIR, self.transfer_id))

        self.handle = open(self._part_filepath, "wb")

    def close(self):
        """Close the handle and rename file to be completed"""
        self.handle.close()
        # move the file into the extracted_files/Coredumps/ if it does not exist already.
        # Otherwise keep it in the trasfer_id subdirectory and remove the ".part" suffix
        if self.error is False:
            final_name = os.path.join(FULL_EXTRACT_DIR, self.filename)
            if not os.path.exists(final_name):
                os.rename(self._part_filepath, final_name)
                try:
                    os.rmdir(os.path.dirname(self._part_filepath))
                except OSError:
                    pass
            else:
                os.rename(self._part_filepath, os.path.join(os.path.dirname(self._part_filepath), self.filename))

    def __repr__(self):
        return self.filename


class ExtractFilesPlugin(Plugin):
    """Extracting all files from DLT trace"""

    message_filters = [("SYS", "FILE"), ("FLT", "FILE")]

    extracted_files = {}
    success = False

    counter = 0

    def __call__(self, message):
        if message.apid in ["SYS", "FLT"] and message.ctid == "FILE":
            # file transfer payload header
            #  FLST - file trasfer start - first DLT message from the file transfer
            #          ["FLST", transfer_id, filename, length, date, "FLST"]
            #  FLDA - file data
            #          ["FLDA", transfer_id, index, data, "FLDA"]
            #  FLFI - file transfer end
            #          ["FLFI", transfer_id, "FLFI"]
            payload_header = message.payload[0].decode('utf8')
            transfer_id = str(message.payload[1])  # used as a dictionary key
            if payload_header == "FLST":
                filename = message.payload[2].decode('utf8')
                filename = os.path.basename(filename)  # ignore whatever path is included in DLT
                logger.info("Found file '%s' in the trace", filename)
                extr_file = File(transfer_id=transfer_id, filename=filename)
                self.extracted_files[transfer_id] = extr_file
            elif payload_header == "FLDA":
                extr_file = self.extracted_files[transfer_id]
                extr_file.index += 1
                if extr_file.index != message.payload[2]:
                    if not extr_file.error:
                        logger.error("Expected index %d, got %d, failing file %s",
                                     extr_file.index, message.payload[2], extr_file.filename)
                    extr_file.error = True
                extr_file.handle.write(message.payload[3])
            elif payload_header == "FLFI":
                extr_file = self.extracted_files[transfer_id]
                extr_file.finished = True
                extr_file.close()

    def report(self):
        bad_files = []
        text = "extracted files found:\n"
        sorted_extracted_files = OrderedDict(sorted(self.extracted_files.items()))
        successful_attachments = [
            os.path.join(COREDUMP_DIR, x.filename)
            for x in sorted_extracted_files.values()
            if not x.error and x.finished
        ]

        for extr_file in sorted_extracted_files.values():
            text += " - {}".format(extr_file.filename)
            if extr_file.error:
                bad_files.append(extr_file.filename)
                text += " ERROR: File parts missing!"
            if extr_file.finished is False:
                if os.path.join(COREDUMP_DIR, extr_file.filename) in successful_attachments:
                    # another file transfer of the same file succeeded
                    logger.warning("File '%s' is not complete", extr_file.filename)
                else:  # file hasn't been re-transferred - error
                    bad_files.append(extr_file.filename)
                    logger.error("File '%s' is not complete", extr_file.filename)
                    text += " ERROR: File not complete!"
            text += "\n"

        if bad_files:
            self.add_result(state="error", message="Error extracting {} files".format(len(set(bad_files))),
                            stdout=text, attach=successful_attachments)
        else:
            self.add_result(stdout=text, attach=successful_attachments)
