"""Mission planner SSE route."""
from __future__ import annotations

import os
from urllib import request as urllib_request

from .providers import _fetch_openrouter_models, _ssl_context


def post(handler, parts: list[str], query: dict):
    body = handler._read_json_body()
    prompt = body.get("prompt")
    approved_models = body.get("approved_models") or []
    workspaces = body.get("workspaces") or ([body.get("workspace")] if body.get("workspace") else [])
    if not isinstance(prompt, str) or not prompt.strip():
        return 400, {"error": "prompt is required"}

    openrouter_key = None
    anthropic_key = None
    try:
        import keyring

        try:
            openrouter_key = keyring.get_password("agentforce-provider", "openrouter")
        except Exception:
            pass
        if not openrouter_key:
            try:
                anthropic_key = keyring.get_password("agentforce", "anthropic")
            except Exception:
                pass
    except Exception:
        pass
    if not anthropic_key:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if not openrouter_key and not anthropic_key:
        return 400, {"error": "no AI provider configured — add an OpenRouter key in Models settings"}

    model = (approved_models[0] if isinstance(approved_models, list) and approved_models
             else ("anthropic/claude-sonnet-4-6" if openrouter_key else "claude-sonnet-4-5"))
    system_prompt = (
        "You are AgentForce's mission planner. Output valid YAML only in the "
        "AgentForce mission format. Do not wrap the YAML in markdown fences, "
        "comments, or prose."
    )
    workspace_info = ", ".join(workspaces) if workspaces else "not specified"
    user_prompt = (
        f"Workspaces: {workspace_info}\n\n"
        f"Approved models: {approved_models}\n\n"
        f"User prompt:\n{prompt}\n"
    )

    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()

    try:
        if openrouter_key:
            payload = {
                "model": model,
                "stream": True,
                "max_tokens": 4096,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            req = urllib_request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=__import__("json").dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://agentforce.local",
                    "X-Title": "AgentForce",
                },
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = __import__("json").loads(data_str)
                        content = chunk["choices"][0].get("delta", {}).get("content", "")
                        if content:
                            handler.wfile.write(f"data: {content}\n\n".encode("utf-8"))
                            handler.wfile.flush()
                    except Exception:
                        pass
        else:
            from anthropic import Anthropic

            client = Anthropic(api_key=anthropic_key)
            with client.messages.stream(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ) as stream:
                for chunk in stream.text_stream:
                    if not chunk:
                        continue
                    handler.wfile.write(f"data: {chunk}\n\n".encode("utf-8"))
                    handler.wfile.flush()
    except Exception as exc:
        try:
            handler.wfile.write(f"data: {str(exc)}\n\n".encode("utf-8"))
            handler.wfile.flush()
        except OSError:
            pass
    finally:
        try:
            handler.wfile.write(b"data: [DONE]\n\n")
            handler.wfile.flush()
        except OSError:
            pass

    return 200, None
