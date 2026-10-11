from app.data.catalog import IndianSecurityCatalog

def test_bse_parser_maps_active_security():
    payload = {"Table": [{"scrip_id": "EXAMPLE", "Scrip_Name": "Example Industries Ltd", "SCRIP_CD": "543210", "ISIN_NUMBER": "INE000000000", "GROUP": "B"}]}
    rows = IndianSecurityCatalog._parse_bse(payload)
    assert rows[0]["symbol"] == "EXAMPLE"
    assert rows[0]["exchange"] == "BSE"
    assert rows[0]["bse_code"] == "543210"
