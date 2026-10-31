import re

import eyewall


def test_version_is_zerover():
    assert re.fullmatch(r"0\.\d+\.\d+", eyewall.__version__), "ZeroVer: the major version stays 0"
