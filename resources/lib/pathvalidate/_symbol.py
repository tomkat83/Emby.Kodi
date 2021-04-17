"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>
"""

import re
from typing import Sequence

from ._common import ascii_symbols, preprocess, unprintable_ascii_chars
from .error import InvalidCharError


__RE_UNPRINTABLE = re.compile(
    "[{}]".format(re.escape("".join(unprintable_ascii_chars))), re.UNICODE
)
__RE_SYMBOL = re.compile(
    "[{}]".format(re.escape("".join(ascii_symbols + unprintable_ascii_chars))), re.UNICODE
)


def validate_unprintable(text: str) -> None:
    # deprecated
    match_list = __RE_UNPRINTABLE.findall(preprocess(text))
    if match_list:
        raise InvalidCharError("unprintable character found: {}".format(match_list))


def replace_unprintable(text: str, replacement_text: str = "") -> str:
    # deprecated
    try:
        return __RE_UNPRINTABLE.sub(replacement_text, preprocess(text))
    except (TypeError, AttributeError):
        raise TypeError("text must be a string")


def validate_symbol(text: str) -> None:
    """
    Verifying whether symbol(s) included in the ``text`` or not.

    Args:
        text:
            Input text to validate.

    Raises:
        ValidationError (ErrorReason.INVALID_CHARACTER):
            If symbol(s) included in the ``text``.
    """

    match_list = __RE_SYMBOL.findall(preprocess(text))
    if match_list:
        raise InvalidCharError("invalid symbols found: {}".format(match_list))


def replace_symbol(
    text: str,
    replacement_text: str = "",
    exclude_symbols: Sequence[str] = [],
    is_replace_consecutive_chars: bool = False,
    is_strip: bool = False,
) -> str:
    """
    Replace all of the symbols in the ``text``.

    Args:
        text:
            Input text.
        replacement_text:
            Replacement text.
        exclude_symbols:
            Symbols that exclude from the replacement.
        is_replace_consecutive_chars:
            If |True|, replace consecutive multiple ``replacement_text`` characters
            to a single character.
        is_strip:
            If |True|, strip ``replacement_text`` from the beginning/end of the replacement text.

    Returns:
        A replacement string.

    Example:

        :ref:`example-sanitize-symbol`
    """

    if exclude_symbols:
        regexp = re.compile(
            "[{}]".format(
                re.escape(
                    "".join(set(ascii_symbols + unprintable_ascii_chars) - set(exclude_symbols))
                )
            ),
            re.UNICODE,
        )
    else:
        regexp = __RE_SYMBOL

    try:
        new_text = regexp.sub(replacement_text, preprocess(text))
    except TypeError:
        raise TypeError("text must be a string")

    if not replacement_text:
        return new_text

    if is_replace_consecutive_chars:
        new_text = re.sub("{}+".format(re.escape(replacement_text)), replacement_text, new_text)

    if is_strip:
        new_text = new_text.strip(replacement_text)

    return new_text
