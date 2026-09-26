from qdojo.combat import api


class FakeHandler:

    def __init__(self, peer, headers):
        self.client_address = (peer, 12345)
        self.headers = headers


def handler_cls():
    for v in vars(api).values():
        if isinstance(v, type) and hasattr(v, "client_ip"):
            return v
    raise AssertionError("no handler with client_ip")


def ip(peer, **headers):
    h = FakeHandler(peer, {k.replace("_", "-"): v for k, v in headers.items()})
    return handler_cls().client_ip(h)


def test_forwarded_for_from_a_client_is_never_trusted():
    assert ip("203.0.113.9", X_Forwarded_For="1.2.3.4") == "203.0.113.9"
    assert ip("100.101.145.1", X_Forwarded_For="1.2.3.4") == "100.101.145.1"


def test_real_client_ip_counts_only_from_a_trusted_proxy():
    assert ip("100.101.145.1", X_Real_Client_IP="198.51.100.7") == "198.51.100.7"
    assert ip("172.18.0.3", X_Real_Client_IP="2001:db8::1") == "2001:db8::1"
    assert ip("203.0.113.9", X_Real_Client_IP="198.51.100.7") == "203.0.113.9"


def test_prefix_lookalikes_are_not_trusted():
    # "100." and "172." prefixes used to be trusted wholesale.
    assert ip("100.200.0.1", X_Real_Client_IP="198.51.100.7") == "100.200.0.1"
    assert ip("172.64.1.1", X_Real_Client_IP="198.51.100.7") == "172.64.1.1"


def test_garbage_client_header_falls_back_to_the_peer():
    assert ip("127.0.0.1", X_Real_Client_IP="not-an-ip, 1.2.3.4") == "127.0.0.1"
