from ansible_flow_mcp.catalog import get_module_schema, list_collections, search_modules


def test_search_modules_ping():
    hits = search_modules("ping")
    assert any(h["fqcn"] == "ansible.builtin.ping" for h in hits)


def test_get_schema_file():
    schema = get_module_schema("ansible.builtin.file")
    assert schema is not None
    names = {o["name"] for o in schema["options"]}
    assert "path" in names
    assert "state" in names


def test_list_collections():
    cols = list_collections()
    assert "ansible.builtin" in cols
