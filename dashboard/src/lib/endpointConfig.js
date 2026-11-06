const LLM_FIELDS = ['endpoint_url', 'model', 'api_type', 'supports_images', 'context_window_tokens', 'chat_reasoning_effort', 'web_reasoning_effort', 'insecure_http_confirmed_url', 'private_endpoint_confirmed_url'];

export function endpointPayload(llm, apiKey, clearApiKey) {
  const connection = Object.fromEntries(LLM_FIELDS.filter((key) => llm[key] !== undefined).map((key) => [key, llm[key]]));
  connection.endpoint_url = (llm.endpoint_url || '').trim();
  if (clearApiKey) connection.api_key_clear = true;
  else if (apiKey) connection.api_key = apiKey;
  return { llm: connection };
}

export function aiConnectionPayload(ai) {
  return {
    ai_provider: ai.ai_provider || 'auto',
    ai_model: ai.ai_model || null,
    ai_webhook_name: ai.ai_webhook_name || null,
    ai_webhook_icon: ai.ai_webhook_icon || null,
  };
}

export const GEMINI_MODELS = [
  { id: 'gemma-4-26b-a4b-it', name: 'Gemma 4 · 26B A4B' },
  { id: 'gemma-4-31b-it', name: 'Gemma 4 · 31B' },
];
