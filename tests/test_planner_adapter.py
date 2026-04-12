from agentforce.server import planner_adapter


def test_parse_planner_response_accepts_bare_mission_spec_without_assistant_message():
    response_text = """
I’m checking the mission-spec shape before returning the updated draft.
{"name":"Weather Mission","goal":"Return the current weather conditions for an Australian city.","definition_of_done":["Page returns current conditions for a selected Australian city."],"tasks":[],"caps":{}}
""".strip()

    assistant_message, draft_spec = planner_adapter._parse_planner_response(response_text)

    assert assistant_message == "Planner draft updated."
    assert draft_spec["name"] == "Weather Mission"
