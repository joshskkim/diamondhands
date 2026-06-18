"""Tool tests: verify each async tool hits the expected endpoint/params and that HTTP
failures surface as ``{"error": ...}`` rather than raising."""

import httpx
import respx

from diamond_mcp import client, server

BASE = client.config.API_BASE_URL


@respx.mock
async def test_get_today_games_hits_endpoint():
    route = respx.get(f"{BASE}/api/games/today").mock(
        return_value=httpx.Response(200, json=[{"gameId": 1}])
    )
    assert await server.get_today_games() == [{"gameId": 1}]
    assert route.called


@respx.mock
async def test_get_best_plays_caps_limit_and_passes_date():
    route = respx.get(f"{BASE}/api/odds/best").mock(return_value=httpx.Response(200, json=[]))
    await server.get_best_plays(date="2026-06-18")
    request = route.calls.last.request
    assert request.url.params["limit"] == "15"
    assert request.url.params["date"] == "2026-06-18"


@respx.mock
async def test_omitted_date_is_not_sent():
    route = respx.get(f"{BASE}/api/props/board").mock(return_value=httpx.Response(200, json={}))
    await server.get_prop_board()
    assert "date" not in route.calls.last.request.url.params


@respx.mock
async def test_search_player_caps_limit():
    route = respx.get(f"{BASE}/api/players/search").mock(return_value=httpx.Response(200, json=[]))
    await server.search_player(name="judge")
    params = route.calls.last.request.url.params
    assert params["name"] == "judge"
    assert params["limit"] == "8"


@respx.mock
async def test_get_player_combines_detail_and_recent():
    respx.get(f"{BASE}/api/players/592450").mock(
        return_value=httpx.Response(200, json={"fullName": "Aaron Judge"})
    )
    recent = respx.get(f"{BASE}/api/players/592450/recent").mock(
        return_value=httpx.Response(200, json=[{"hits": 2}])
    )
    result = await server.get_player(player_id=592450)
    assert result["player"]["fullName"] == "Aaron Judge"
    assert result["recent"] == [{"hits": 2}]
    assert recent.calls.last.request.url.params["limit"] == "15"


@respx.mock
async def test_path_params_interpolated():
    route = respx.get(f"{BASE}/api/games/42/projections").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert await server.get_game_projections(game_id=42) == {"ok": True}
    assert route.called


@respx.mock
async def test_http_error_becomes_error_dict():
    respx.get(f"{BASE}/api/games/today").mock(return_value=httpx.Response(503))
    result = await server.get_today_games()
    assert "error" in result
    assert "503" in result["error"]


@respx.mock
async def test_network_error_becomes_error_dict():
    respx.get(f"{BASE}/api/games/today").mock(side_effect=httpx.ConnectError("refused"))
    result = await server.get_today_games()
    assert "error" in result


@respx.mock
async def test_game_briefing_fans_out_and_merges():
    proj = respx.get(f"{BASE}/api/games/7/projections").mock(
        return_value=httpx.Response(200, json={"batters": []})
    )
    odds = respx.get(f"{BASE}/api/games/7/odds").mock(
        return_value=httpx.Response(200, json={"markets": []})
    )
    result = await server.get_game_briefing(game_id=7)
    assert result == {"projections": {"batters": []}, "odds": {"markets": []}}
    assert proj.called and odds.called


@respx.mock
async def test_slate_summary_fans_out_three():
    respx.get(f"{BASE}/api/games/today").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE}/api/odds/best").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE}/api/props/board").mock(return_value=httpx.Response(200, json={}))
    result = await server.get_slate_summary()
    assert set(result) == {"games", "best_plays", "prop_board"}


async def test_all_tools_registered():
    # 10 Ask-Diamond mirror + 10 richer + 2 composite = 22
    tools = await server.mcp.list_tools()
    assert len(tools) == 22
    names = {t.name for t in tools}
    assert "search_player" in names
    assert "get_pitch_type_leaderboard" in names
    assert "get_game_briefing" in names
    assert "get_slate_summary" in names
