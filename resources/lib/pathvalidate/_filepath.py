"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>
"""

import ntpath
import os.path
import posixpath
import re
from pathlib import Path
from typing import List, Optional, Pattern, Tuple  # noqa

from ._base import AbstractSanitizer, BaseFile, BaseValidator
from ._common import (
    PathType,
    Platform,
    PlatformType,
    findall_to_str,
    is_pathlike_obj,
    preprocess,
    validate_pathtype,
)
from ._const import _NTFS_RESERVED_FILE_NAMES
from ._filename import FileNameSanitizer, FileNameValidator
from .error import (
    ErrorReason,
    InvalidCharError,
    InvalidLengthError,
    ReservedNameError,
    ValidationError,
)


_RE_INVALID_PATH = re.compile("[{:s}]".format(re.escape(BaseFile._INVALID_PATH_CHARS)), re.UNICODE)
_RE_INVALID_WIN_PATH = re.compile(
    "[{:s}]".format(re.escape(BaseFile._INVALID_WIN_PATH_CHARS)), re.UNICODE
)


class FilePathSanitizer(AbstractSanitizer):
    def __init__(
        self,
        min_len: Optional[int] = 1,
        max_len: Optional[int] = None,
        platform: PlatformType = None,
        check_reserved: bool = True,
        normalize: bool = True,
    ) -> None:
        super().__init__(
            min_len=min_len,
            max_len=max_len,
            check_reserved=check_reserved,
            platform=platform,
        )

        self._sanitize_regexp = self._get_sanitize_regexp()
        self.__fpath_validator = FilePathValidator(
            min_len=self.min_len,
            max_len=self.max_len,
            check_reserved=check_reserved,
            platform=self.platform,
        )
        self.__fname_sanitizer = FileNameSanitizer(
            min_len=self.min_len,
            max_len=self.max_len,
            check_reserved=check_reserved,
            platform=self.platform,
        )
        self.__normalize = normalize

        if self._is_universal() or self._is_windows():
            self.__split_drive = ntpath.splitdrive
        else:
            self.__split_drive = posixpath.splitdrive

    def sanitize(self, value: PathType, replacement_text: str = "") -> PathType:
        if not value:
            return ""

        self.__fpath_validator.validate_abspath(value)

        unicode_filepath = preprocess(value)

        if self.__normalize:
            unicode_filepath = os.path.normpath(unicode_filepath)

        drive, unicode_filepath = self.__split_drive(unicode_filepath)
        sanitized_path = self._sanitize_regexp.sub(replacement_text, unicode_filepath)
        if self._is_windows():
            path_separator = "\\"
        else:
            path_separator = "/"

        sanitized_entries = []  # type: List[str]
        if drive:
            sanitized_entries.append(drive)
        for entry in sanitized_path.replace("\\", "/").split("/"):
            if entry in _NTFS_RESERVED_FILE_NAMES:
                sanitized_entries.append("{}_".format(entry))
                continue

            sanitized_entry = str(self.__fname_sanitizer.sanitize(entry))
            if not sanitized_entry:
                if not sanitized_entries:
                    sanitized_entries.append("")
                continue

            sanitized_entries.append(sanitized_entry)

        sanitized_path = path_separator.join(sanitized_entries)

        if is_pathlike_obj(value):
            return Path(sanitized_path)

        return sanitized_path

    def _get_sanitize_regexp(self) -> Pattern:
        if self.platform in [Platform.UNIVERSAL, Platform.WINDOWS]:
            return _RE_INVALID_WIN_PATH

        return _RE_INVALID_PATH


class FilePathValidator(BaseValidator):
    _RE_NTFS_RESERVED = re.compile(
        "|".join("^/{}$".format(re.escape(pattern)) for pattern in _NTFS_RESERVED_FILE_NAMES),
        re.IGNORECASE,
    )
    _MACOS_RESERVED_FILE_PATHS = ("/", ":")

    @property
    def reserved_keywords(self) -> Tuple[str, ...]:
        common_keywords = super().reserved_keywords

        if any([self._is_universal(), self._is_posix(), self._is_macos()]):
            return common_keywords + self._MACOS_RESERVED_FILE_PATHS

        if self._is_linux():
            return common_keywords + ("/",)

        return common_keywords

    def __init__(
        self,
        min_len: Optional[int] = 1,
        max_len: Optional[int] = None,
        platform: PlatformType = None,
        check_reserved: bool = True,
    ) -> None:
        super().__init__(
            min_len=min_len,
            max_len=max_len,
            check_reserved=check_reserved,
            platform=platform,
        )

        self.__fname_validator = FileNameValidator(
            min_len=min_len, max_len=max_len, check_reserved=check_reserved, platform=platform
        )

        if self._is_universal() or self._is_windows():
            self.__split_drive = ntpath.splitdrive
        else:
            self.__split_drive = posixpath.splitdrive

    def validate(self, value: PathType) -> None:
        validate_pathtype(
            value,
            allow_whitespaces=False
            if self.platform in [Platform.UNIVERSAL, Platform.WINDOWS]
            else True,
        )
        self.validate_abspath(value)

        _drive, value = self.__split_drive(str(value))
        if not value:
            return

        filepath = os.path.normpath(value)
        unicode_filepath = preprocess(filepath)
        value_len = len(unicode_filepath)

        if value_len > self.max_len:
            raise InvalidLengthError(
                "file path is too long: expected<={:d}, actual={:d}".format(self.max_len, value_len)
            )
        if value_len < self.min_len:
            raise InvalidLengthError(
                "file path is too short: expected>={:d}, actual={:d}".format(
                    self.min_len, value_len
                )
            )

        self._validate_reserved_keywords(unicode_filepath)
        unicode_filepath = unicode_filepath.replace("\\", "/")
        for entry in unicode_filepath.split("/"):
            if not entry or entry in (".", ".."):
                continue

            self.__fname_validator._validate_reserved_keywords(entry)

        if self._is_universal() or self._is_windows():
            self.__validate_win_filepath(unicode_filepath)
        else:
            self.__validate_unix_filepath(unicode_filepath)

    def validate_abspath(self, value: PathType) -> None:
        value = str(value)
        is_posix_abs = posixpath.isabs(value)
        is_nt_abs = ntpath.isabs(value)
        err_object = ValidationError(
            description=(
                "an invalid absolute file path ({}) for the platform ({}).".format(
                    value, self.platform.value
                )
                + " to avoid the error, specify an appropriate platform correspond"
                + " with the path format, or 'auto'."
            ),
            platform=self.platform,
            reason=ErrorReason.MALFORMED_ABS_PATH,
        )

        if any([self._is_windows() and is_nt_abs, self._is_linux() and is_posix_abs]):
            return

        if self._is_universal() and any([is_posix_abs, is_nt_abs]):
            ValidationError(
                description=(
                    "{}. expected a platform independent file path".format(
                        "POSIX absolute file path found"
                        if is_posix_abs
                        else "NT absolute file path found"
                    )
                ),
                platform=self.platform,
                reason=ErrorReason.MALFORMED_ABS_PATH,
            )

        if any([self._is_windows(), self._is_universal()]) and is_posix_abs:
            raise err_object

        drive, _tail = ntpath.splitdrive(value)
        if not self._is_windows() and drive and is_nt_abs:
            raise err_object

    def __validate_unix_filepath(self, unicode_filepath: str) -> None:
        match = _RE_INVALID_PATH.findall(unicode_filepath)
        if match:
            raise InvalidCharError(
                self._ERROR_MSG_TEMPLATE.format(
                    invalid=findall_to_str(match), value=repr(unicode_filepath)
                )
            )

    def __validate_win_filepath(self, unicode_filepath: str) -> None:
        match = _RE_INVALID_WIN_PATH.findall(unicode_filepath)
        if match:
            raise InvalidCharError(
                self._ERROR_MSG_TEMPLATE.format(
                    invalid=findall_to_str(match), value=repr(unicode_filepath)
                ),
                platform=Platform.WINDOWS,
            )

        _drive, value = self.__split_drive(unicode_filepath)
        if value:
            match_reserved = self._RE_NTFS_RESERVED.search(value)
            if match_reserved:
                reserved_name = match_reserved.group()
                raise ReservedNameError(
                    "'{}' is a reserved name".format(reserved_name),
                    reusable_name=False,
                    reserved_name=reserved_name,
                    platform=self.platform,
                )


def validate_filepath(
    file_path: PathType,
    platform: Optional[str] = None,
    min_len: int = 1,
    max_len: Optional[int] = None,
    check_reserved: bool = True,
) -> None:
    """Verifying whether the ``file_path`` is a valid file path or not.

    Args:
        file_path:
            File path to validate.
        platform:
            Target platform name of the file path.

            .. include:: platform.txt
        min_len:
            Minimum length of the ``file_path``. The value must be greater or equal to one.
            Defaults to ``1``.
        max_len:
            Maximum length of the ``file_path`` length. If the value is |None|,
            automatically determined by the ``platform``:

                - ``Linux``: 4096
                - ``macOS``: 1024
                - ``Windows``: 260
                - ``universal``: 260
        check_reserved:
            If |True|, check reserved names of the ``platform``.

    Raises:
        ValidationError (ErrorReason.INVALID_CHARACTER):
            If the ``file_path`` includes invalid char(s):
            |invalid_file_path_chars|.
            The following characters are also invalid for Windows platform:
            |invalid_win_file_path_chars|
        ValidationError (ErrorReason.INVALID_LENGTH):
            If the ``file_path`` is longer than ``max_len`` characters.
        ValidationError:
            If ``file_path`` include invalid values.

    Example:
        :ref:`example-validate-file-path`

    See Also:
        `Naming Files, Paths, and Namespaces - Win32 apps | Microsoft Docs
        <https://docs.microsoft.com/en-us/windows/win32/fileio/naming-a-file>`__
    """

    FilePathValidator(
        platform=platform, min_len=min_len, max_len=max_len, check_reserved=check_reserved
    ).validate(file_path)


def validate_file_path(file_path, platform=None, max_path_len=None):
    # Deprecated
    validate_filepath(file_path, platform, max_path_len)


def is_valid_filepath(
    file_path: PathType,
    platform: Optional[str] = None,
    min_len: int = 1,
    max_len: Optional[int] = None,
    check_reserved: bool = True,
) -> bool:
    """Check whether the ``file_path`` is a valid name or not.

    Args:
        file_path:
            A filepath to be checked.

    Example:
        :ref:`example-is-valid-filepath`

    See Also:
        :py:func:`.validate_filepath()`
    """

    return FilePathValidator(
        platform=platform, min_len=min_len, max_len=max_len, check_reserved=check_reserved
    ).is_valid(file_path)


def sanitize_filepath(
    file_path: PathType,
    replacement_text: str = "",
    platform: Optional[str] = None,
    max_len: Optional[int] = None,
    check_reserved: bool = True,
    normalize: bool = True,
) -> PathType:
    """Make a valid file path from a string.

    To make a valid file path the function does:

        - replace invalid characters for a file path within the ``file_path``
          with the ``replacement_text``. Invalid characters are as follows:

            - unprintable characters
            - |invalid_file_path_chars|
            - for Windows (or universal) only: |invalid_win_file_path_chars|

        - Append underscore (``"_"``) at the tail of the name if sanitized name
          is one of the reserved names by operating systems
          (only when ``check_reserved`` is |True|).

    Args:
        file_path:
            File path to sanitize.
        replacement_text:
            Replacement text for invalid characters.
            Defaults to ``""``.
        platform:
            Target platform name of the file path.

            .. include:: platform.txt
        max_len:
            Maximum length of the ``file_path`` length. Truncate the name if the ``file_path``
            length exceedd this value. If the value is |None|,
            ``max_len`` will automatically determined by the ``platform``:

                - ``Linux``: 4096
                - ``macOS``: 1024
                - ``Windows``: 260
                - ``universal``: 260
        check_reserved:
            If |True|, sanitize reserved names of the ``platform``.
        normalize:
            If |True|, normalize the the file path.

    Returns:
        Same type as the argument (str or PathLike object):
            Sanitized filepath.

    Raises:
        ValueError:
            If the ``file_path`` is an invalid file path.

    Example:
        :ref:`example-sanitize-file-path`
    """

    return FilePathSanitizer(
        platform=platform, max_len=max_len, check_reserved=check_reserved, normalize=normalize
    ).sanitize(file_path, replacement_text)


def sanitize_file_path(file_path, replacement_text="", platform=None, max_path_len=None):
    # Deprecated
    return sanitize_filepath(file_path, platform, max_path_len)
