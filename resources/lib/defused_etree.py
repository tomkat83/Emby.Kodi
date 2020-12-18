#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
xml.etree.ElementTree tries to encode with text.encode('ascii') - which is
just plain BS. This etree will always return unicode, not string
"""
# Originally tried faster cElementTree, but does NOT work reliably with Kodi
from defusedxml.ElementTree import DefusedXMLParser, _generate_etree_functions

from xml.etree.ElementTree import TreeBuilder as _TreeBuilder
from xml.etree.ElementTree import parse as _parse
from xml.etree.ElementTree import iterparse as _iterparse
from xml.etree.ElementTree import tostring


class UnicodeXMLParser(DefusedXMLParser):
    """
    PKC Hack to ensure we're always receiving unicode, not str
    """
    @staticmethod
    def _fixtext(text):
        """
        Do NOT try to convert every entry to str with entry.encode('ascii')!
        """
        return text


# aliases
XMLTreeBuilder = XMLParse = UnicodeXMLParser

parse, iterparse, fromstring = _generate_etree_functions(UnicodeXMLParser,
                                                         _TreeBuilder, _parse,
                                                         _iterparse)
XML = fromstring


__all__ = ['XML', 'XMLParse', 'XMLTreeBuilder', 'fromstring', 'iterparse',
           'parse', 'tostring']
