from origin.compile import compile_event
from origin.geometry import buffer_ok
from origin.models import EventRecord, Parcel
from origin.seed import PARCELS
from datetime import datetime, timezone


def _parcel(pid: str) -> Parcel:
    _, label, crop, area, ring, buf = next(p for p in PARCELS if p[0] == pid)
    return Parcel(
        id=pid,
        farm_id="demo-farm",
        lpis_id="x",
        label=label,
        crop=crop,
        area_ha=area,
        geom={"type": "Polygon", "coordinates": [ring + [ring[0]]]},
        watercourse_buffer_m=buf,
    )


def _parcel3() -> Parcel:
    return _parcel("p3")


def test_compile_excludes_yield(tmp_path, monkeypatch):
    from origin import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "origin.json")
    event = EventRecord(
        id="e1",
        farm_id="demo-farm",
        parcel_id="p3",
        time=datetime.now(timezone.utc),
        product_name="X",
        rate=1.2,
        buffer_m=5,
        status="confirmed",
    )
    pack = compile_event(event, _parcel3())
    assert "yield" not in pack.fields
    assert pack.fields["product_name"] == "X"
    assert pack.fields["buffer_ok"] is True


def test_us_buffer_check_fails_without_buffer(tmp_path, monkeypatch):
    from origin import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "origin.json")
    event = EventRecord(
        id="e2",
        farm_id="demo-farm",
        parcel_id="p3",
        time=datetime.now(timezone.utc),
        product_name="X",
        rate=1.2,
        buffer_m=0,
        status="confirmed",
    )
    pack = compile_event(event, _parcel3())
    assert pack.fields["buffer_ok"] is False


def test_shared_corner_is_not_frontage():
    """p4 starts exactly where the ditch ends, at (220, 80).

    A single shared point is not a bank you can leave a filter strip on, so p4
    must pass with no buffer claimed. p3, which the ditch runs through, must not.
    """
    corner = buffer_ok(_parcel("p4"), 0.0)
    assert corner["touches_watercourse"] is False
    assert corner["frontage_m"] < 1.0
    assert corner["required_m"] == 0.0
    assert corner["buffer_ok"] is True

    real = buffer_ok(_parcel3(), 0.0)
    assert real["touches_watercourse"] is True
    assert real["frontage_m"] > 200
    assert real["buffer_ok"] is False


def test_distant_field_needs_no_buffer():
    """p1 stops 10 m short of the ditch. Distance is recorded for the audit trail."""
    away = buffer_ok(_parcel("p1"), 0.0)
    assert away["touches_watercourse"] is False
    assert away["distance_m"] == 10.0
    assert away["buffer_ok"] is True
