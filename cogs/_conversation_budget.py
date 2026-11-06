"""Fit recent chat into Strata's text window without discarding required context."""
import json
import hashlib
from collections import OrderedDict
from time import monotonic

import aiohttp

from cogs._llm_moderation import auxiliary_url, endpoint_json
from cogs._llm_responses import responses_input

CONTEXT_CEILING = 262144
OUTPUT_RESERVE = 1000
TEMPLATE_MARGIN = 2048
IMAGE_RESERVE = 16384  # Estimated headroom per image; native text counts exclude vision preprocessing.
MAX_TEXT_BYTES = 2 * 1024 * 1024


class ContextBudgetError(ValueError):
    pass


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


def _newest_suffix(turns, byte_budget):
    selected, used = [], 0
    for turn in reversed(turns):
        size = len(_dump(turn).encode("utf-8")) + 2
        if used + size > byte_budget:
            break
        selected.append(turn)
        used += size
    return list(reversed(selected))


class ConversationBudget:
    def __init__(self):
        self.metadata = OrderedDict()
        self.unavailable_counts = OrderedDict()

    @staticmethod
    def connection_key(cfg):
        return cfg.get("api_type", "chat_completions"), cfg["endpoint_url"], cfg["model"], cfg.get("context_window_tokens", CONTEXT_CEILING), hashlib.sha256((cfg.get("api_key") or "").encode()).digest()

    async def window(self, session, cfg):
        key = self.connection_key(cfg)
        cached = self.metadata.get(key)
        if cached and monotonic() - cached[0] < 300:
            self.metadata.move_to_end(key)
            return cached[1]
        window = cfg.get("context_window_tokens", CONTEXT_CEILING)
        if session is not None and auxiliary_url(cfg["endpoint_url"], "models", api_type=cfg.get("api_type", "chat_completions")):
            try:
                result = await endpoint_json(session, cfg, auxiliary="models")
                for model in result.get("data", []) if isinstance(result, dict) else []:
                    if not isinstance(model, dict):
                        continue
                    if model.get("id") == cfg["model"]:
                        metadata = model.get("meta") or {}
                        reported = metadata.get("n_ctx") if isinstance(metadata, dict) else None
                        if type(reported) is int and reported > 0:
                            window = min(window, reported)
                        break
            except (ValueError, KeyError, TypeError, aiohttp.ClientError, TimeoutError):
                pass
        self.metadata[key] = (monotonic(), window)
        self.metadata.move_to_end(key)
        while len(self.metadata) > 32:
            self.metadata.popitem(last=False)
        return window

    async def count(self, session, cfg, prompt, context, image_text, *, current=None):
        api_type = cfg.get("api_type", "chat_completions")
        route = "responses/input_tokens" if api_type == "responses" else "messages/count_tokens"
        if session is None or auxiliary_url(cfg["endpoint_url"], route, api_type=api_type) is None:
            return None
        key = self.connection_key(cfg)
        unavailable = self.unavailable_counts.get(key)
        if unavailable is not None and monotonic() - unavailable < 300:
            self.unavailable_counts.move_to_end(key)
            return None
        self.unavailable_counts.pop(key, None)
        if current and not await current():
            return None
        try:
            content = [{"type": "text", "text": _dump(context)}, *image_text]
            if api_type == "responses":
                payload = {"model": cfg["model"], "input": responses_input([
                    {"role": "system", "content": prompt}, {"role": "user", "content": content}])}
            else:
                payload = {"model": cfg["model"], "system": prompt,
                    "messages": [{"role": "user", "content": content}], "thinking": {"type": "disabled"}}
            result = await endpoint_json(session, cfg, payload, auxiliary=route)
            tokens = result.get("input_tokens") if isinstance(result, dict) else None
            return tokens if type(tokens) is int and tokens >= 0 else None
        except ValueError as exc:
            if str(exc) in {"endpoint_http_404", "endpoint_http_405", "endpoint_http_501"}:
                self.unavailable_counts[key] = monotonic()
                while len(self.unavailable_counts) > 32:
                    self.unavailable_counts.popitem(last=False)
            return None
        except (KeyError, TypeError, aiohttp.ClientError, TimeoutError):
            return None

    async def replay_allowance(self, session, cfg):
        window = await self.window(session, cfg)
        available = window - cfg.get("output_reserve", OUTPUT_RESERVE) - TEMPLATE_MARGIN
        return min(MAX_TEXT_BYTES, max(0, available))

    async def replay_fits(self, session, cfg, messages, *, tools=None):
        # Include opaque encrypted output bytes; never truncate required replay items.
        size = len(_dump(messages).encode("utf-8")) + (len(_dump(tools).encode("utf-8")) if tools else 0)
        return size <= await self.replay_allowance(session, cfg)

    async def research_allowance(self, session, cfg, prompt, context, image_parts, *, current=None):
        """Reserve the authorized conversation before allocating space to public passages."""
        window = await self.window(session, cfg)
        image_text = [part for part in image_parts if part.get("type") == "text"]
        tokens = await self.count(session, cfg, prompt, context, image_text, current=current)
        if tokens is None:
            tokens = len((prompt + _dump(context) + "".join(part["text"] for part in image_text)).encode("utf-8"))
        remaining = (window - tokens - cfg.get("output_reserve", OUTPUT_RESERVE) - TEMPLATE_MARGIN
                     - sum(part.get("type") == "image_url" for part in image_parts) * IMAGE_RESERVE)
        if remaining < min(8192, window // 10) and context.get("conversation_untrusted"):
            # Old chat can be trimmed again by fit after research; required rules/current text cannot.
            required = {**context, "conversation_untrusted": []}
            required_tokens = await self.count(session, cfg, prompt, required, image_text, current=current)
            if required_tokens is None:
                required_tokens = len((prompt + _dump(required) + "".join(part["text"] for part in image_text)).encode("utf-8"))
            remaining = (window - required_tokens - cfg.get("output_reserve", OUTPUT_RESERVE) - TEMPLATE_MARGIN
                         - sum(part.get("type") == "image_url" for part in image_parts) * IMAGE_RESERVE)
        # JSON framing, search results and the final ledger share the remaining 40 percent.
        return min(192000, max(0, int(remaining * .6)))

    async def fit(self, session, cfg, prompt, context, image_parts, *, current=None, before_count=None):
        if current and not await current():
            return None
        window = await self.window(session, cfg)
        images = sum(part.get("type") == "image_url" for part in image_parts)
        available = window - cfg.get("output_reserve", OUTPUT_RESERVE) - TEMPLATE_MARGIN - images * IMAGE_RESERVE
        if available <= 0:
            raise ContextBudgetError("context_required_exceeds_window")
        image_text = [part for part in image_parts if part.get("type") == "text"]
        turns = context.get("conversation_untrusted", [])
        required = {**context, "conversation_untrusted": []}
        required_bytes = len((prompt + _dump(required) + "".join(part["text"] for part in image_text)).encode("utf-8"))
        max_bytes = min(MAX_TEXT_BYTES, available * 8)
        if required_bytes > max_bytes:
            raise ContextBudgetError("context_required_exceeds_payload_limit")
        full = {**context, "conversation_untrusted": turns}
        full_bytes = len((prompt + _dump(full) + "".join(part["text"] for part in image_text)).encode("utf-8"))
        if current and not await current():
            return None
        # A complete UTF-8 bound avoids both token-count HTTP and its authorization fetch.
        if full_bytes <= min(MAX_TEXT_BYTES, available):
            return full
        candidate = full if full_bytes <= max_bytes else {**required,
            "conversation_untrusted": _newest_suffix(turns, max_bytes - required_bytes)}
        tokens = await self.count(session, cfg, prompt, candidate, image_text, current=before_count)
        if tokens is None:
            # UTF-8 bytes are a conservative text bound, not an exact tokenizer count.
            if required_bytes > available:
                raise ContextBudgetError("context_required_exceeds_fallback_window")
            return {**required, "conversation_untrusted": _newest_suffix(turns, available - required_bytes)}
        if tokens <= available:
            return candidate
        if not candidate["conversation_untrusted"]:
            raise ContextBudgetError("context_required_exceeds_window")
        required_tokens = await self.count(session, cfg, prompt, required, image_text, current=before_count)
        if required_tokens is None:
            if required_bytes > available:
                raise ContextBudgetError("context_required_exceeds_fallback_window")
            return {**required, "conversation_untrusted": _newest_suffix(turns, available - required_bytes)}
        if required_tokens > available:
            raise ContextBudgetError("context_required_exceeds_window")
        for _ in range(2):
            history = candidate["conversation_untrusted"]
            history_bytes = sum(len(_dump(turn).encode("utf-8")) + 2 for turn in history)
            fraction = max(0, (available - required_tokens) / max(1, tokens - required_tokens)) * 0.90
            reduced = _newest_suffix(history, int(history_bytes * min(0.9, fraction)))
            if not reduced:
                return required
            candidate = {**required, "conversation_untrusted": reduced}
            if current and not await current():
                return None
            tokens = await self.count(session, cfg, prompt, candidate, image_text, current=before_count)
            if tokens is None:
                if required_bytes <= available:
                    return {**required, "conversation_untrusted": _newest_suffix(turns, available - required_bytes)}
                return required
            if tokens <= available:
                return candidate
        # Required context was counted successfully; never send an unchecked oversized candidate.
        return required
