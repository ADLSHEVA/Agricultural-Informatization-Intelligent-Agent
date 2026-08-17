from origin.compile import compile_event
from origin.models import EventRecord, Parcel
from origin.seed import PARCELS
from datetime import datetime, timezone


def _parcel3() -> Parcel:
    pid, label, crop, area, ring, buf = next(p for p in PARCELS if p[0] == "p3")
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
    eu = compile_event(event, _parcel3(), rule_id="coop_ppp_statement_v1")
    assert eu.fields["gaec4_buffer_ok"] is True
    assert eu.partner_id == "loire-cereals-coop"


def test_gaec4_fails_without_buffer(tmp_path, monkeypatch):
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
