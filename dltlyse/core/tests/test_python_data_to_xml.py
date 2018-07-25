# Copyright (C) 2017, BMW Car IT GmbH. All rights reserved.
"""Tests for data_to_xml_string plugin for dltlyse."""
from unittest import TestCase

from dltlyse.core.utils import data_to_xml_string


class TestDataToXMLString(TestCase):
    """data_to_xml_string unit tests."""

    def test_only_the_tag_present(self):
        """Tests that only the tag is present."""
        data = 'foo'
        self.assertEqual(data_to_xml_string(data), '''<?xml version="1.0" ?>
<foo/>
''')

    def test_tag_and_value_present(self):
        """Tests that the tag and value are present."""
        data = 'foo', 'bar'
        self.assertEqual(data_to_xml_string(data), '''<?xml version="1.0" ?>
<foo>bar</foo>
''')

    def test_tag_and_attributes_present(self):
        """Tests that the tag and attributes are present."""
        data = 'foo', {'bar': '123'}
        self.assertEqual(data_to_xml_string(data), '''<?xml version="1.0" ?>
<foo bar="123"/>
''')

    def test_tag_and_attributes_and_value_present(self):  # pylint: disable=invalid-name
        """Tests that the tag, attributes, and value are present."""
        data = 'foo', {'bar': '123'}, 'spam'
        self.assertEqual(data_to_xml_string(data), '''<?xml version="1.0" ?>
<foo bar="123">spam</foo>
''')

    def test_value_is_a_tuple(self):
        """Tests that the value is a tuple which generates sub-tags."""
        data = 'foo', ('bar', 'spam')
        self.assertEqual(data_to_xml_string(data), '''<?xml version="1.0" ?>
<foo>
\t<bar/>
\t<spam/>
</foo>
''')

    def test_value_is_a_list(self):
        """Tests that the value is a list which generates sub-tags."""
        data = 'foo', ['bar', 'spam']
        self.assertEqual(data_to_xml_string(data), '''<?xml version="1.0" ?>
<foo>
\t<bar/>
\t<spam/>
</foo>
''')

    def test_value_is_not_a_string(self):
        """Tests that the value is not a string.

        It can be any value, that can be converted to a string. A float is used for the test.
        """
        data = 'foo', 1.5
        self.assertEqual(data_to_xml_string(data), '''<?xml version="1.0" ?>
<foo>1.5</foo>
''')

    def test_children_with_complex_data_structure(self):  # pylint: disable=invalid-name
        """Tests that children can use the same rules of the main tag.

        It allows to easily define more complex data structures.
        """
        data = 'foo', ['bar', ('spam', 123), ('droogs', {'milk': 'plus'})]
        self.assertEqual(data_to_xml_string(data), '''<?xml version="1.0" ?>
<foo>
\t<bar/>
\t<spam>123</spam>
\t<droogs milk="plus"/>
</foo>
''')

    def test_children_with_the_same_tag_name(self):  # pylint: disable=invalid-name
        """Tests that the tag name for children can be defined just ones.

        When all children share the same tag name, it's possible to define it once (with the
        special $tag attribute), and then it'll be automatically used by all of them.
        """
        data = 'foo', {'$tag': 'bar'}, [1, 2, 3]
        self.assertEqual(data_to_xml_string(data), '''<?xml version="1.0" ?>
<foo>
\t<bar>1</bar>
\t<bar>2</bar>
\t<bar>3</bar>
</foo>
''')

    def test_children_with_the_same_attributes(self):  # pylint: disable=invalid-name
        """Tests that the attributes for children can be defined just ones.

        When all children share the same attributes, it's possible to define them once (with the
        special $attr attribute), and then they'll be automatically used by all of them.
        """
        data = 'foo', {'$attr': {'bar': 'spam'}}, ['droogs', 'milk', 'plus']
        self.assertEqual(data_to_xml_string(data), '''<?xml version="1.0" ?>
<foo>
\t<droogs bar="spam"/>
\t<milk bar="spam"/>
\t<plus bar="spam"/>
</foo>
''')

    def test_children_with_the_same_name_and_attributes(self):  # pylint: disable=invalid-name
        """Tests that the tag name and attributes for children can be defined just ones.

        When all children share the same name and attributes, it's possible to define them once
        (with the special $tag and $attr attributes), and then they'll be automatically used by all
        of them.
        """
        data = 'foo', {'$tag': 'bar', '$attr': {'milk': 'plus'}}, [1, 2, 3]
        self.assertEqual(data_to_xml_string(data), '''<?xml version="1.0" ?>
<foo>
\t<bar milk="plus">1</bar>
\t<bar milk="plus">2</bar>
\t<bar milk="plus">3</bar>
</foo>
''')
