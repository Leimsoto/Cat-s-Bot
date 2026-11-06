"""Stateless Responses wire format; application tool authorization stays with callers."""
import json


def response_choice(result):
    if not isinstance(result, dict) or result.get("status") != "completed" or result.get("error") is not None or result.get("incomplete_details") is not None:
        raise ValueError("endpoint_incomplete_response")
    output = result.get("output")
    if not isinstance(output, list) or not output:
        raise ValueError("endpoint_invalid_response_output")
    texts, calls = [], []
    for item in output:
        if not isinstance(item, dict) or item.get("status") not in (None, "completed"):
            raise ValueError("endpoint_invalid_response_item")
        kind = item.get("type")
        if kind == "message":
            if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
                raise ValueError("endpoint_invalid_response_message")
            for part in item["content"]:
                if not isinstance(part, dict):
                    raise ValueError("endpoint_invalid_response_content")
                if part.get("type") == "refusal":
                    raise ValueError("endpoint_response_refused")
                if part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                    raise ValueError("endpoint_invalid_response_content")
                texts.append(part["text"])
        elif kind == "function_call":
            try:
                arguments = json.loads(item.get("arguments"))
            except (ValueError, TypeError, RecursionError):
                raise ValueError("endpoint_invalid_tool_call") from None
            if not isinstance(arguments, dict):
                raise ValueError("endpoint_invalid_tool_call")
            calls.append({"id": item.get("call_id"), "type": "function",
                          "function": {"name": item.get("name"), "arguments": item.get("arguments")}})
        elif kind == "reasoning":
            if item.get("encrypted_content") is not None and not isinstance(item["encrypted_content"], str):
                raise ValueError("endpoint_invalid_reasoning_item")
            if not isinstance(item.get("summary", []), list):
                raise ValueError("endpoint_invalid_reasoning_item")
        else:
            raise ValueError("endpoint_unoffered_response_item")
    return {"finish_reason": "tool_calls" if calls else "stop",
            "message": {"content": "".join(texts) if texts else None, "tool_calls": calls}}, output


def responses_input(messages):
    items, pending, seen = [], set(), set()
    for message in messages:
        role = message["role"]
        if role == "tool":
            call_id = message.get("tool_call_id")
            if call_id not in pending or not isinstance(message.get("content"), str):
                raise ValueError("endpoint_unmatched_tool_output")
            pending.remove(call_id)
            items.append({"type": "function_call_output", "call_id": call_id, "output": message["content"]})
            continue
        if pending:
            raise ValueError("endpoint_missing_tool_output")
        if role == "assistant" and "_responses_output" in message:
            _, replay = response_choice({"status": "completed", "output": message["_responses_output"]})
            items.extend(replay)
            calls = [item for item in replay if item["type"] == "function_call"]
        else:
            if role not in {"system", "developer", "user", "assistant"}:
                raise ValueError("endpoint_invalid_input_role")
            content = message.get("content")
            if isinstance(content, list):
                parts = []
                for part in content:
                    if part.get("type") == "text" and isinstance(part.get("text"), str):
                        parts.append({"type": "input_text", "text": part["text"]})
                    elif part.get("type") == "image_url" and isinstance(part.get("image_url"), dict):
                        source = part["image_url"]
                        if not isinstance(source.get("url"), str):
                            raise ValueError("endpoint_invalid_input_image")
                        image = {"type": "input_image", "image_url": source["url"]}
                        if "detail" in source:
                            image["detail"] = source["detail"]
                        parts.append(image)
                    else:
                        raise ValueError("endpoint_invalid_input_content")
                items.append({"role": role, "content": parts})
            elif isinstance(content, str):
                items.append({"role": role, "content": content})
            elif content is not None:
                raise ValueError("endpoint_invalid_input_content")
            calls = [{"type": "function_call", "call_id": call["id"], **call["function"]}
                     for call in message.get("tool_calls", [])]
            items.extend(calls)
        for call in calls:
            call_id = call.get("call_id")
            if not isinstance(call_id, str) or not call_id or call_id in seen:
                raise ValueError("endpoint_invalid_replayed_tool_call")
            pending.add(call_id)
            seen.add(call_id)
    if pending:
        raise ValueError("endpoint_missing_tool_output")
    return items


def responses_payload(model, messages, *, moderation=False, tools=None):
    payload = {"model": model, "input": responses_input(messages),
               "max_output_tokens": 512 if moderation else 1000, "store": False}
    if moderation:
        payload["text"] = {"format": {"type": "json_object"}}
    elif tools:
        payload["tools"] = []
        for tool in tools:
            if tool.get("type") != "function" or not isinstance(tool.get("function"), dict):
                raise ValueError("endpoint_invalid_tool_definition")
            definition = {"type": "function", **tool["function"]}
            definition.setdefault("strict", False)
            payload["tools"].append(definition)
        payload["tool_choice"] = "auto"
        payload["include"] = ["reasoning.encrypted_content"]
    return payload
