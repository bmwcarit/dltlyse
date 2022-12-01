# Copyright (C) 2022. BMW Car IT GmbH. All rights reserved.
"""Helper functions"""

import atexit
import logging
import os
import tempfile
from decimal import Decimal
import xml.dom.minidom
from xml.etree.ElementTree import Element, SubElement, tostring as xml_element_to_string

logger = logging.getLogger(__name__)

dlt_example_stream = (
    b"DLT\x01#o\xd1WD>\x0c\x00MGHS5\x00\x00YMGHS\x00\x01\x80\xd1&\x01DA1\x00DC1\x00\x03\x00\x00\x00"
    b"\x07\x01\x00SYS\x00\x01\x00FILE\xff\xff\x16\x00File transfer manager.\x12\x00"
    b"DLT System ManagerremoDLT\x01#o\xd1Wo>\x0c\x00MGHS=\x00\x01PMGHS\x00\x00\x03\xf4\x00"
    b"\x01i\xa6A\x05SYS\x00JOUR\x00\x02\x00\x00\x1b\x002011/11/11 11:11:18.005274\x00\x00\x02\x00\x00"
    b"\t\x006.005274\x00\x00\x02\x00\x00\x16\x00systemd-journal[748]:\x00\x00\x02\x00\x00\x0f\x00"
    b"Informational:\x00\x00\x02\x00\x00\xcf\x00Runtime journal (/run/log/journal/) is currently"
    b" using 8.0M.\nMaximum allowed usage is set to 385.9M.\nLeaving at least 578.8M free (of"
    b" currently available 3.7G of space).\nEnforced usage limit is thus 385.9M.\x00"
)

file_with_two_lifecycles = (
    b"DLT\x01\xc5\x82\xdaX\x82o\x0e\x00MG1S=\x00\x00NMG1S"  # first lifecycle
    b"\x00\x00\x02r\x00\x00\x8frA\x01DLTDINTM\x00\x02\x00\x00.\x00"
    b"Daemon launched. Starting to output traces...\x00"
    b"DLT\x01m\xc2\x91Y\x9f\xda\x07\x00MGHS5\x00\x00 MGHS"  # no new lifecycle
    b"\x00\x00_\xde&\x01DA1\x00DC1\x00\x02\x0f\x00\x00\x00\x02\x00\x00\x00\x00"
    b"DLT\x01m\xc2\x91Y\xad\xe4\x07\x00MGHS=\x01\x00zMGHS"  # random trace
    b"\x00\x00\x02\xab\x00\x00@VA\x01DLTDINTM\x00\x02\x00\x00Z\x00"
    b"ApplicationID 'DBSY' registered for PID 689, Description=DBus"
    b" Logging|SysInfra|Log&Trace\n\x00"
    b"DLT\x01\xed\xc2\x91Y\x0f\xf0\x08\x00MGHS5\x00\x00 MGHS"  # trace to buffer
    b"\x00\x00\x9dC&\x01DA1\x00DC1\x00\x02\x0f\x00\x00\x00\x02\x00\x00\x00\x00"
    b"DLT\x01\xed\xc2\x91Y\x17.\n\x00MG2S=\x00\x00NMG2S"  # new lifecycle
    b"\x00\x00\x02\xae\x00\x00@/A\x01DLTDINTM\x00\x02\x00\x00.\x00"
    b"Daemon launched. Starting to output traces...\x00"
)

file_with_lifecycles_without_start = (
    b"DLT\x01\xc5\x82\xdaX\x19\x93\r\x00XORA'\x01\x00\x1bXORA"  # trace to buffer
    b"\x16\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x11\x04\x00\x00\x00\x00"
    b"DLT\x01\xc5\x82\xdaXQi\x0e\x00MGHS5\x00\x00 MGHS"  # trace to buffer
    b"\x00\x03U\xe0&\x01DA1\x00DC1\x00\x02\x0f\x00\x00\x00\x02\x00\x00\x00\x00"
    b"DLT\x01m\xc2\x91Y\xad\xe4\x07\x00MGHS=\x01\x00zMGHS"  # random trace
    b"\x00\x00\x02\xab\x00\x00@VA\x01DLTDINTM\x00\x02\x00\x00Z\x00"
    b"ApplicationID 'DBSY' registered for PID 689, Description=DBus"
    b" Logging|SysInfra|Log&Trace\n\x00"
    b"DLT\x01\xed\xc2\x91Y\x0f\xf0\x08\x00MGHS5\x00\x00 MGHS"  # trace to buffer
    b"\x00\x00\x9dC&\x01DA1\x00DC1\x00\x02\x0f\x00\x00\x00\x02\x00\x00\x00\x00"
    b"DLT\x01\xed\xc2\x91Y\x17.\n\x00MG3S=\x00\x00NMG3S"  # new lifecycle
    b"\x00\x00\x02\xae\x00\x00@/A\x01DLTDINTM\x00\x02\x00\x00.\x00"
    b"Daemon launched. Starting to output traces...\x00"
)

single_random_dlt_message = bytearray(
    b"DLT\x01m\xc2\x91Y\xad\xe4\x07\x00MGHS=\x01\x00zMGHS"  # random trace
    b"\x00\x00\x02\xab\x00\x00@VA\x01DLTDINTM\x00\x02\x00\x00Z\x00"
    b"ApplicationID 'DBSY' registered for PID 689, Description=DBus"
    b" Logging|SysInfra|Log&Trace\n\x00"
)

start_dlt_message = bytearray(
    b"DLT\x01\xed\xc2\x91Y\x17.\n\x00MGHS=\x00\x00NMGHS"  # new lifecycle
    b"\x00\x00\x02\xae\x00\x00@/A\x01DLTDINTM\x00\x02\x00\x00.\x00"
    b"Daemon launched. Starting to output traces...\x00"
)

single_random_corrupt_dlt_message = bytearray(
    b"\x00\x00\x02\xab\x00\x00@VA\x01DLTDINTM\x00\x02\x00\x00Z\x00"  # random corrupt trace
    b"ApplicationID 'DBSY' registered for PID 689, Description=DBus"
    b" Logging|SysInfra|Log&Trace\n\x00"
)

single_bufferable_trace_1 = bytearray(
    b"DLT\x01\xc5\x82\xdaX\x19\x93\r\x00XORA'\x01\x00\x1bXORA"  # trace to buffer
    b"\x16\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x11\x04\x00\x00\x00\x00"
)

single_bufferable_trace_2 = bytearray(
    b"DLT\x01\xc5\x82\xdaXQi\x0e\x00MGHS5\x00\x00 MGHS"  # trace to buffer
    b"\x00\x03U\xe0&\x01DA1\x00DC1\x00\x02\x0f\x00\x00\x00\x02\x00\x00\x00\x00"
)


def seconds_to_human_readable(seconds):
    """Splits seconds and returns a string in the form hr:min:secs.ms"""
    secs, msecs = divmod(seconds, 1)
    mins, secs = divmod(int(seconds), 60)
    hrs, mins = divmod(mins, 60)
    return "{:d}:{:02d}:{:02d}.{:02.0f}".format(hrs, mins, secs, msecs * 100)


def data_to_xml_tree(data, parent=None, child_tag=None, child_attrib=None):
    """Converts a Python structure in an ElementTree structure.

    The key concept when using this function is that for generating a valid XML ElementData, three
    information should be available: tag, attributes, and value/children. Some of such information
    can be omitted if it's optional (so, not specified) or if it can be already extracted by the
    context. Of course, at least the tag information should be provided in some way.
    Usually a tuple of three elements is passed to fully qualify all three required data.

    For example, passing ('foo', {'bar': '123'}, 'spam'), as the data parameter, generates an
    ElementTree structure which, once converted to string, looks like:
    <foo bar="123">spam</foo>

    To generate only a node with the tag, it's enough to call the function with only
    a string as parameter (the tag). For example, 'foo' gives back:
    <foo/>
    That's because no tuple was provided, but only a basic primitive (a string), and since the tag
    is mandatory, it's automatically assumed that the string has to be used as the tag.

    Instead, passing the tuple ('foo', 'bar') generates:
    <foo>bar</foo>
    In this case the second element should contain either the attributes or the value(s) of the tag,
    but since it's not a dictionary (the only data type which can used to specify the list of
    attributes with their values), it's automatically assumed to be used as the value.

    Finally, passing ('foo', {'bar': '123'}) generates:
    <foo bar="123"/>
    That's because the two elements tuple has not enough information, but the second element is a
    dictionary, so it's automatically used for the tag's attributes.

    A list or tuple can also be passed as the tag's value, and in this case a deeper XML structure
    is generated. For example, passing ('foo', ['bar', 'spam']) generates:
    <foo>
        <bar/>
        <spam/>
    </foo>

    To each list's element is applied the same logic defined before, so a tuple/list can be passed
    as well, to better qualify each sub-tag. For example, passing
    ('foo', ['bar', ('spam', 123), ('droogs', {'milk': 'plus'})]) generates:
    <foo>
        <bar/>
        <spam>123</spam>
        <droogs milk="plus"/>
    </foo>

    Sometimes the sub-tags share the same tag name, so a mechanism is defined in order to avoid to
    specify it for all of them. In this case, a special key in the main tag's attributes can be
    used: '$tag'. For example, ('foo', {'$tag': 'bar'}, [1, 2, 3]) generates:
    <foo>
        <bar>1</bar>
        <bar>2</bar>
        <bar>3</bar>
    </foo>
    So, the application can focus on providing only the concrete data that should be generated.

    Similarly, if the sub-tags use the same attributes sets, a special key in the main tag's
    attributes can be used: '$attr'. For example,
    ('foo', {'$attr': {'bar': 'spam'}}, ['droogs', 'milk', 'plus']) generates:
    <foo>
        <droogs bar="spam"/>
        <milk bar="spam"/>
        <plus bar="spam"/>
    </foo>

    A combination of $tag and $attr can be used as well, so passing
    ('foo', {'$tag': 'bar', '$attr': {'milk': 'plus'}}, [1, 2, 3]) generates:
    <foo>
        <bar milk="plus">1</bar>
        <bar milk="plus">2</bar>
        <bar milk="plus">3</bar>
    </foo>

    Finally, it has to be noted that if the value information isn't a list or tuple, it'll be
    automatically converted to a string. For example, ('foo', datetime.datetime.now()) generates:
    <foo>2017-02-20 09:20:12.746000</foo>

    Args:
        data(list, tuple, dict, or any type): the Python data structure. See above for more details.
        parent(Element): the parent node (if available).
        child_tag(str, None): the tag to be used for direct children (if any).
        child_attrib(dict, None): the attributes to to be used for direct children (if any).
    """
    # print('data_to_xml_tree: data={}, parent={}, child_tag={}, child_attrib={}'.format(
    #     data, parent, child_tag, child_attrib), file=out)
    attrib, value = {}, None
    if child_tag:  # Have: tag. Miss: attrib, value
        tag, child_tag = child_tag, None
        if child_attrib is not None:  # Have: tag, attrib. Miss: value
            attrib, child_attrib, value = child_attrib, {}, data
        else:  # Have: tag, Miss: attrib, value
            if isinstance(data, dict):
                attrib = data
            elif isinstance(data, (tuple, list)):
                if len(data) == 2:
                    attrib, value = data
                else:
                    tag, attrib, value = data[:3]
            else:
                value = data
    else:  # Miss: tag, attrib, value
        if child_attrib is not None:  # Have: attrib. Miss: tag, value
            attrib, child_attrib = child_attrib, {}
            if isinstance(data, (tuple, list)):
                if len(data) == 2:
                    tag, value = data
                else:
                    tag, attrib, value = data[:3]
            else:
                tag = data
        else:  # Miss: tag, attrib, value
            if isinstance(data, (tuple, list)):
                if len(data) == 2:
                    tag, data = data
                    if isinstance(data, dict):
                        attrib = data
                    else:
                        value = data
                else:
                    tag, attrib, value = data[:3]
            else:
                tag = data

    if attrib:
        # The original attribute dictionary should be preserved, because it might be used by other
        # tags. That's because we'll remove some keys, if they are present. See below.
        attrib = attrib.copy()

        new_child_tag = attrib.pop("$tag", None)
        if new_child_tag is not None:
            child_tag = new_child_tag
        new_child_attrib = attrib.pop("$attr", None)
        if new_child_attrib is not None:
            child_attrib = new_child_attrib

    text, children = (
        (None, value) if isinstance(value, (tuple, list)) else (str(value) if value is not None else None, ())
    )
    node = Element(tag, attrib) if parent is None else SubElement(parent, tag, attrib)
    if text is not None:
        node.text = text
    for child in children:
        data_to_xml_tree(child, node, child_tag, child_attrib)

    return node


def data_to_xml_string(data, prettify=True, indent="\t", newline="\n"):
    """Generates an XML string representation of a Python structure according to data_to_xml_tree.

    Args:
        data(list, tuple, dict, or any type): the Python data structure. See data_to_xml_tree.
        prettify(bool): True if the XML string should be reformatted with a nice output.
        indent(str): the string to be used for indenting the XML elements.
        newline(str): the string to be used when an XML element is complete.
    """
    xml_string = xml_element_to_string(data_to_xml_tree(data))
    if prettify:
        xml_data = xml.dom.minidom.parseString(xml_string)
        xml_string = xml_data.toprettyxml(indent, newline)

    return xml_string


def create_temp_dlt_file(stream=None, dlt_message=None, empty=False):
    """Creates temporary DLT trace files for testing purposes

    Args:
        stream: A byte stream variable containing a stream in byte hex format
        dlt_message(DLTMessage object): A dlt message object to be converted into temporary file
        empty(bool): True will just create an empty DLT file
    """
    _, tmpname = tempfile.mkstemp()
    if empty:
        return tmpname
    msg = ()
    if dlt_message:
        msg = dlt_message.to_bytes()
    else:
        msg = stream

    tmpfile = open(tmpname, "wb")
    tmpfile.write(msg)
    tmpfile.flush()
    tmpfile.seek(0)
    tmpfile.close()

    atexit.register(os.remove, tmpname)

    return tmpname


def round_float(val, precision=4):
    """Rounds off the floating point number to correct precision
        regardless of underlying platform floating point precision

    Args:
        val(float): The value that needs to be rounded off
        precision(int): Number of decimal places to round off
    """
    decimal_points = Decimal(10) ** -(precision)
    result_val = Decimal(val).quantize(decimal_points)
    return result_val if result_val.normalize() == result_val.to_integral() else result_val.normalize()
