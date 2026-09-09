from ansible_flow_mcp.http_health import doctor_report


def test_doctor_report_has_ok_and_version():
    report = doctor_report()
    assert "ok" in report
    assert report["version"]
    assert report["catalogDir"]
    assert isinstance(report["galleryCount"], int)
