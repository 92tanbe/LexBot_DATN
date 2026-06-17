from app.services.cypher_safety import validate_readonly_cypher


def test_cypher_safety_blocks_write():
    try:
        validate_readonly_cypher("MATCH (a:Article) DELETE a")
    except ValueError:
        return
    raise AssertionError("write cypher was not blocked")
