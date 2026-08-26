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


def test_local_status_compare_and_set_does_not_overwrite_terminal_state(local_store):
    local_store.put("agent_runs", "run-cas", {"id": "run-cas", "status": "completed"})
    changed = local_store.put_if_status(
        "agent_runs",
        "run-cas",
        {"id": "run-cas", "status": "waiting_for_farmer"},
        {"running"},
    )
    assert changed is False
    assert local_store.get("agent_runs", "run-cas")["status"] == "completed"
