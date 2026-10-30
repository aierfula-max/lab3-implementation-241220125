"""pytest 公共夹具。"""

from __future__ import annotations

import pytest

from tests.factories import make_org


@pytest.fixture()
def org():
    item = make_org()
    yield item
    item.app.close()
