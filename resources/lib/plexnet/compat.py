# -*- coding: utf-8 -*-
"""
Python 2/3 compatability
Always try Py3 first
"""

try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode

try:
    from urllib.parse import quote
except ImportError:
    from urllib import quote

try:
    from urllib.parse import quote_plus
except ImportError:
    from urllib import quote_plus

try:
    from configparser import ConfigParser
except ImportError:
    from ConfigParser import ConfigParser
