import test from 'node:test';
import assert from 'node:assert/strict';
import { endpointPayload, aiConnectionPayload } from './endpointConfig.js';

test('empty key preserves credentials and payload excludes moderation state and secrets', () => {
  const payload = endpointPayload({ endpoint_url: ' https://example.test/v1 ', model: 'model', enabled: true, rules_text: 'rules', api_key: 'stored-secret', api_key_configured: true }, '', false);
  assert.equal(payload.llm.endpoint_url, 'https://example.test/v1');
  assert.equal('api_key' in payload.llm, false);
  assert.equal('enabled' in payload.llm, false);
  assert.equal('rules_text' in payload.llm, false);
  assert.equal('api_key_configured' in payload.llm, false);
});

test('replacement and explicit deletion have distinct payloads', () => {
  assert.equal(endpointPayload({}, 'new-key', false).llm.api_key, 'new-key');
  const cleared = endpointPayload({}, '', true).llm;
  assert.equal(cleared.api_key_clear, true);
  assert.equal('api_key' in cleared, false);
});

test('connection patch cannot overwrite IA behavior and keeps manual token value', () => {
  assert.deepEqual(aiConnectionPayload({ ai_provider: 'strata', ai_model: 'gemma', ai_webhook_name: 'Name', ai_webhook_icon: '', ai_enabled: 0, ai_web_enabled: 0 }), { ai_provider: 'strata', ai_model: 'gemma', ai_webhook_name: 'Name', ai_webhook_icon: null });
  assert.equal(endpointPayload({context_window_tokens: 524288}, '', false).llm.context_window_tokens, 524288);
  assert.equal(endpointPayload({context_window_tokens: 350000}, '', false).llm.context_window_tokens, 350000);
});
