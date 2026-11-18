from atra.schemagen import drift, generated_files


def test_contract_files_match_the_code():
    stale = drift(generated_files())
    assert not stale, "run `python -m atra.schemagen`: " + ", ".join(p.name for p in stale)


def _refs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def _resolve(doc, ref):
    node = doc
    for part in ref.removeprefix("#/").split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def test_every_openapi_reference_resolves():
    import yaml

    from atra.config import ROOT

    for path in sorted((ROOT / "contracts" / "openapi").glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        for ref in set(_refs(doc)):
            assert ref.startswith("#/"), (path.name, ref)
            _resolve(doc, ref)
