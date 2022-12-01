# Copyright (C) 2022. BMW Car IT GmbH. All rights reserved.
"""Helpers for dltlyse plugin testing"""


class MockDLTMessage(object):
    """Mock DLT message for dltlyse plugin testing"""

    def __init__(self, ecuid="MGHS", apid="SYS", ctid="JOUR", sid="958", payload="", tmsp=0.0, sec=0, msec=0, mcnt=0):
        self.ecuid = ecuid
        self.apid = apid
        self.ctid = ctid
        self.sid = sid
        self.payload = payload
        self.tmsp = tmsp
        self.mcnt = mcnt
        self.storageheader = MockStorageHeader(sec=sec, msec=msec)

    def compare(self, target):
        """Compare DLT Message to a dictionary"""
        return target == {k: v for k, v in self.__dict__.items() if k in target.keys()}

    @property
    def payload_decoded(self):
        """Fake payload decoding"""
        return self.payload

    def __repr__(self):
        return str(self.__dict__)


class MockStorageHeader(object):
    """Mock DLT storage header for plugin testing"""

    def __init__(self, msec=0, sec=0):
        self.microseconds = msec
        self.seconds = sec
