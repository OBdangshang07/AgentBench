from agentbench.service import _viewer_safe_event_payload


def test_viewer_events_strip_reasoning_prompts_and_secrets():
    model_event = _viewer_safe_event_payload(
        "model.responded",
        {
            "step": 4,
            "kind": "tool",
            "content": "private reasoning with sk-example-secret-123456789",
            "usage": {"input_tokens": 12, "output_tokens": 8},
        },
    )
    assert "content" not in model_event
    assert model_event["usage"] == {"input_tokens": 12, "output_tokens": 8}

    tool_event = _viewer_safe_event_payload(
        "tool.requested",
        {
            "step": 5,
            "name": "shell",
            "arguments": {
                "command": "curl -H 'Authorization: Bearer abcdefghijklmnop' localhost",
                "content": "hidden file body",
            },
        },
    )
    rendered = str(tool_event)
    assert "abcdefghijklmnop" not in rendered
    assert "hidden file body" not in rendered
    assert tool_event["arguments"]["content_bytes"] > 0


def test_viewer_events_do_not_expose_private_validator_evidence():
    event = _viewer_safe_event_payload(
        "validator.completed",
        {
            "validator_type": "command",
            "score": 80,
            "status": "partial",
            "evidence": {"private_input": "hidden answer", "stdout": "secret"},
        },
    )
    assert event == {"validator_type": "command", "score": 80, "status": "partial"}
