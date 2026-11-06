"""Bounded, extractive proposals; identity and storage authority belong to code."""
import re
import unicodedata


PERSONAL_MEMORY_TOOL = [{"type": "function", "function": {
    "name": "remember_personal_preference",
    "description": (
        "Optionally remember ONE useful durable non-sensitive self-description explicitly stated in the CURRENT trigger text. "
        "quote must be an exact short first-person quotation, never a summary or inference. Only communication/language preferences, "
        "ordinary hobbies, professional role or learning/personal projects. NEVER secrets, contact/address/financial/health/sexual/religious/"
        "political data, third-party facts, temporary state, quotes, instructions, history, images or web results. "
        "No IDs or scope arguments: code binds the requester and confines storage to this channel. "
        "Do not repeat existing memories. Include your normal answer in assistant content if possible; do not claim it is saved: "
        "the application will notify only after verified storage. Omit this tool when uncertain."),
    "parameters": {"type": "object", "properties": {"quote": {"type": "string", "minLength": 5, "maxLength": 250}},
        "required": ["quote"], "additionalProperties": False}}}]

_SELF = re.compile(r"^(?:soy\b|uso\b|utilizo\b|tengo\b|juego\b|programo\b|aprendo\b|estudio\b|llamame\b|"
    r"prefiero\b|me (?:gustan?|encantan?|interesan?)\b|mi (?:aficion|hobby|profesion|proyecto|idioma)\b|"
    r"trabajo como\b|estoy (?:aprendiendo|desarrollando)\b|i (?:prefer|like|enjoy|work as|am learning|am building)\b|"
    r"i (?:am|use|have|play|study)\b|my (?:hobby|profession|project|language)\b|sou\b|uso\b|prefiro\b|gosto de\b|trabalho como\b|estou a (?:aprender|desenvolver)\b)")
_PRIVATE = re.compile(r"(?:contrase|password|passwd|secret|secreto|token|api.?key|clave|credencial|pin\b|"
    r"direccion|domicilio|address|telefono|phone|email|correo|bank|banco|iban|tarjeta|credit|wallet|"
    r"medic|salud|health|diagnos|terapia|therapy|enferm|disease|tratamiento|depres|ansiedad|anxiety|"
    r"sexual|religio|politic|partido|vote|voto|orientacion|etnia|racial|race\b|sindicato|union\b|cumpleanos|birthday|anos de edad|years old|"
    r"mi (?:amig|pareja|madre|padre|herman|hij|jef|compan)|my (?:friend|partner|mother|father|brother|sister|child|boss)|"
    r"hoy\b|ahora\b|today\b|tomorrow\b|manana\b|esta semana|this week|temporal|\d{5}|https?://|[@<>`\"\n\r])")
_NO_CAPTURE = re.compile(r"(?:no (?:guardes|recuerdes|memorices)|(?:do not|don't) (?:save|remember)|nao (?:guardes|lembre))")


def memory_candidate(arguments, trigger):
    if not isinstance(arguments, dict) or set(arguments) != {"quote"}:
        return None
    quote = arguments["quote"]
    if not isinstance(quote, str) or not 5 <= len(quote) <= 250 or quote != quote.strip():
        return None
    if not isinstance(trigger, str) or quote not in trigger:
        return None
    prefix = trigger[:trigger.index(quote)]
    line_prefix = re.sub(r"<@!?\d+>", "", prefix.rsplit("\n", 1)[-1])
    # Mentions/greetings are ordinary prefixes; cited/code/third-party speech is not evidence.
    if any(marker in line_prefix for marker in ('>', '`', '"', "'", '“', '«', ':')) or "```" in prefix:
        return None
    if re.search(r"\b(?:dijo|dice|dijeron|said|says|wrote|escribio|quote|cita|ejemplo)\b", line_prefix, re.I):
        return None
    normalized = "".join(c for c in unicodedata.normalize("NFKD", quote.casefold()) if not unicodedata.combining(c))
    trigger_normalized = "".join(c for c in unicodedata.normalize("NFKD", trigger.casefold()) if not unicodedata.combining(c))
    # Conservative syntax is an extra guard; semantic eligibility is also required by the tool contract.
    if not _SELF.search(normalized) or _PRIVATE.search(normalized) or _NO_CAPTURE.search(trigger_normalized):
        return None
    return quote
