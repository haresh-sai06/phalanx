from phalanx.browser import Snapshot
from phalanx.detectors import detect_all, XSS_PAYLOAD

def _snap(**kw):
    base = dict(url="http://127.0.0.1:5055/", title="", status=200, text="", html="", links=[], forms=[], cookies=[])
    base.update(kw)
    return Snapshot(**base)

def test_404():
    f = detect_all(_snap(url="http://127.0.0.1:5055/help", status=404, title="Not Found"))
    assert any(x.fingerprint == "404:/help" for x in f)

def test_api_404_ignored():
    f = detect_all(_snap(url="http://127.0.0.1:5055/api/rides/1", status=404))
    assert not any(x.fingerprint.startswith("404:") for x in f)

def test_xss():
    html = f"<html><body><b>{XSS_PAYLOAD}</b></body></html>"
    f = detect_all(_snap(url="http://127.0.0.1:5055/estimate?q=x", html=html, text="x"))
    assert any(x.fingerprint == "xss:estimate" for x in f)

def test_admin_and_passwords():
    text = "Users\nPassword\nalice rider alice@example.test alice123\n"
    f = detect_all(_snap(url="http://127.0.0.1:5055/admin", title="Admin panel · RideLite", text=text, html=text))
    fps = {x.fingerprint for x in f}
    assert "authz:admin-open" in fps and "secrets:plaintext-passwords" in fps

def test_idor_list():
    f = detect_all(_snap(url="http://127.0.0.1:5055/rides", text="Owner alice bob Airport"), current_user="bob")
    assert any(x.fingerprint == "idor:rides-list" for x in f)

def test_negative_fare():
    f = detect_all(_snap(url="http://127.0.0.1:5055/rides/1", text="Fare: $-87.50"))
    assert any(x.fingerprint == "validation:negative-tip" for x in f)
