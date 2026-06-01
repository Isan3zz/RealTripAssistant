import json

from travel_planning_agent.tools.poi_parser import parse_poi_briefs, summarize_poi_search


def _mcp_text(payload):
    return [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]


def test_parse_poi_briefs_from_gaode_text_payload():
    payload = {
        "suggestion": {"keywords": "", "ciytes": {"suggestion": []}},
        "pois": [
            {
                "id": "B023B02842",
                "name": "灵隐寺",
                "address": "法云弄1号",
                "typecode": "110202",
                "cityname": "杭州市",
                "adname": "西湖区",
                "biz_ext": {"rating": "4.8", "cost": "30"},
                "photo": "https://example.test/photo.jpg",
            },
            {
                "id": "B023B17XAC",
                "name": "灵隐寺-天王殿",
                "address": "灵隐寺内",
                "typecode": "110205",
            },
        ],
    }

    briefs = parse_poi_briefs(_mcp_text(payload), limit=1)

    assert briefs == [{
        "id": "B023B02842",
        "name": "灵隐寺",
        "address": "法云弄1号",
        "area": "杭州市西湖区",
        "type": "110202",
        "location": "",
        "rating": "4.8",
        "cost": "30",
    }]


def test_summarize_poi_search_removes_verbose_fields():
    payload = {
        "pois": [
            {"id": "1", "name": "西湖", "address": "龙井路1号", "photo": "unused"},
            {"id": "2", "name": "断桥残雪", "address": "西湖景区内", "photo": "unused"},
        ]
    }

    summary = summarize_poi_search(_mcp_text(payload), "杭州", "cultural", limit=2)

    assert "【POI】杭州景点（取前2条）" in summary
    assert "西湖｜龙井路1号" in summary
    assert "photo" not in summary


def test_summarize_empty_poi_result_degrades_cleanly():
    assert summarize_poi_search(_mcp_text({"pois": []}), "杭州", "food") == "【POI】杭州美食: 暂未查到精确结果"
