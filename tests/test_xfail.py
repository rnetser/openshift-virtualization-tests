import pytest


class HighPacketLossError(Exception):
    pass


@pytest.mark.xfail(reason="my reason", run=False)
@pytest.mark.polarion("CNV-111")
def test_1():
    return


@pytest.mark.xfail(reason="quarantined, my reason", run=False)
@pytest.mark.polarion("CNV-112")
def test_2():
    return


@pytest.mark.xfail(
    reason=(
        "Network infrastructure is slow from time to time. "
        "Due to that, test might fail with packet loss greater than 2%"
    ),
    raises=HighPacketLossError,
)
@pytest.mark.polarion("CNV-113")
def test_3():
    return


@pytest.mark.xfail(reason="test4 fail")
@pytest.mark.polarion("CNV-114")
def test_4():
    raise ValueError("yy")
