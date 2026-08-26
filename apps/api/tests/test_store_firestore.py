from origin.store_firestore import _from_firestore, _to_firestore


def test_geojson_polygon_round_trips_without_nested_firestore_arrays():
    polygon = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [10, 0], [10, 5], [0, 0]]],
    }
    source = {"id": "p1", "geom": polygon, "tags": ["corn", "sprayed"]}

    encoded = _to_firestore(source)

    assert encoded["geom"]["encoding"] == "geojson"
    assert isinstance(encoded["geom"]["value"], str)
    assert encoded["tags"] == source["tags"]
    assert _from_firestore(encoded) == source


def test_non_geometry_documents_are_unchanged():
    source = {"id": "run-1", "steps": [{"name": "gate", "status": "done"}]}

    assert _from_firestore(_to_firestore(source)) == source
