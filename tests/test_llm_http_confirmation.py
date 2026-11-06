import asyncio
import json
import ipaddress
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlsplit

from fastapi import HTTPException
import aiohttp

from api.routes.guild import patch_automod_config
from cogs._conversation import endpoint_config
from cogs._llm_moderation import EndpointResolver, endpoint_json, request_completion
from llm_moderation_config import HTTPConfirmationRequired, validate_llm_config
from tests.test_managed_messages import make_db


class HTTPConfirmationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = make_db()
        self.env = patch.dict("os.environ", {"CATBOT_LLM_ALLOWED_HOSTS": ""})
        self.env.start()
        async def addresses(url):
            try:
                return [str(ipaddress.ip_address(urlsplit(url).hostname))]
            except ValueError:
                return ["93.184.216.34"]
        self.dns = patch("api.routes.guild.resolve_endpoint_addresses", side_effect=addresses)
        self.dns.start()

    def tearDown(self):
        self.env.stop()
        self.dns.stop()
        self.db._sqlite_conn.close()

    async def save(self, guild_id, value):
        return await patch_automod_config(guild_id, {"rules": {"llm": value}}, self.db, {})

    async def test_confirmation_is_url_and_guild_specific_and_key_is_preserved(self):
        url, other = "http://model.example/v1", "http://other.example/v1"
        await self.save(1, {"endpoint_url": "https://before.example/v1", "api_key": "private-key"})
        before = self.db.get_automod_config(1)
        with self.assertRaises(HTTPException) as error:
            await self.save(1, {"endpoint_url": url})
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(error.exception.detail["code"], "http_confirmation_required")
        self.assertEqual(error.exception.detail["endpoint_url"], url)
        self.assertNotIn("private-key", str(error.exception.detail))
        self.assertEqual(before, self.db.get_automod_config(1))

        result = await self.save(1, {"endpoint_url": url, "insecure_http_confirmed_url": url})
        llm = result["config"]["rules"]["llm"]
        self.assertEqual(llm["insecure_http_confirmed_url"], url)
        self.assertTrue(llm["api_key_configured"])
        self.assertNotIn("api_key", llm)
        self.assertEqual(endpoint_config(self.db, 1)["endpoint_url"], url)
        self.assertEqual((await self.save(1, {"model": "model-name"}))["config"]["rules"]["llm"]["insecure_http_confirmed_url"], url)
        with self.assertRaises(HTTPException):
            await self.save(2, {"endpoint_url": url})
        with self.assertRaises(HTTPException):
            await self.save(1, {"endpoint_url": other, "insecure_http_confirmed_url": url})
        await self.save(1, {"endpoint_url": other, "insecure_http_confirmed_url": other, "api_key": "new-key"})
        self.assertEqual(self.db.get_automod_config(1)["rules"]["llm"]["api_key"], "new-key")
        result = await self.save(1, {"endpoint_url": "https://secure.example/v1"})
        self.assertEqual(result["config"]["rules"]["llm"]["insecure_http_confirmed_url"], "")
        self.assertTrue(result["config"]["rules"]["llm"]["api_key_configured"])

    def test_legacy_https_config_defaults_match_validated_policy_without_resaving(self):
        legacy = {"enabled": True, "rules_text": "No insultar", "endpoint_url": "https://model.example/v1", "model": "test"}
        self.db._upsert_config("automod_config", 1, enabled=1, rules=json.dumps({"llm": legacy}))
        raw = self.db.get_automod_config(1)["rules"]["llm"]
        self.assertEqual(raw, validate_llm_config(raw))

    def test_http_consent_never_authorizes_private_addresses_and_allowlist_still_works(self):
        for url in ("http://127.0.0.1/v1", "http://192.168.1.20/v1", "http://169.254.169.254/v1", "http://[::1]/v1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_llm_config({"endpoint_url": url, "insecure_http_confirmed_url": url})
        with self.assertRaises(HTTPConfirmationRequired):
            validate_llm_config({"endpoint_url": "http://public.example/v1", "insecure_http_confirmed_url": "http://different.example/v1"})
        with self.assertRaises(ValueError):
            validate_llm_config({"insecure_http_confirmed_url": True})
        with patch.dict("os.environ", {"CATBOT_LLM_ALLOWED_HOSTS": "localhost"}):
            self.assertEqual(validate_llm_config({"endpoint_url": "http://localhost:8080/v1"})["endpoint_url"], "http://localhost:8080/v1")

    async def test_private_config_is_confirmed_per_url_and_dns_public_strips_unused_consent(self):
        url = "http://192.168.1.20:8080/v1"
        with self.assertRaises(HTTPException) as error:
            await self.save(1, {"endpoint_url": url})
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(error.exception.detail["code"], "private_confirmation_required")
        self.assertEqual(error.exception.detail["required_confirmations"], ["http", "private"])
        self.assertEqual(self.db.get_automod_config(1)["rules"]["llm"]["endpoint_url"], "")
        result = await self.save(1, {"endpoint_url": url, "insecure_http_confirmed_url": url, "private_endpoint_confirmed_url": url, "api_key": "private-key"})
        self.assertEqual(result["config"]["rules"]["llm"]["private_endpoint_confirmed_url"], url)
        self.assertNotIn("private-key", json.dumps(result))
        with patch("api.routes.guild.resolve_endpoint_addresses", AsyncMock(side_effect=AssertionError("Unrelated save must not resolve again"))):
            await self.save(1, {"model": "updated"})
        with self.assertRaises(HTTPException):
            await self.save(2, {"endpoint_url": url, "insecure_http_confirmed_url": url})
        public = "http://public.example/custom/completion"
        result = await self.save(1, {"endpoint_url": public, "insecure_http_confirmed_url": public, "private_endpoint_confirmed_url": public})
        cfg = result["config"]["rules"]["llm"]
        self.assertEqual(cfg["private_endpoint_confirmed_url"], "")
        self.assertTrue(cfg["api_key_configured"])

    async def test_private_hostname_confirmation_and_failed_dns_never_persist(self):
        url = "https://local-model.example/v1"
        with patch("api.routes.guild.resolve_endpoint_addresses", AsyncMock(return_value=["10.1.2.3", "fd00::123"])):
            with self.assertRaises(HTTPException) as error:
                await self.save(1, {"endpoint_url": url})
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(error.exception.detail["required_confirmations"], ["private"])
            await self.save(1, {"endpoint_url": url, "private_endpoint_confirmed_url": url})
        before = self.db.get_automod_config(1)
        with patch("api.routes.guild.resolve_endpoint_addresses", AsyncMock(side_effect=ValueError("No se pudo resolver el endpoint; no se ha guardado."))):
            with self.assertRaises(HTTPException) as error:
                await self.save(1, {"endpoint_url": "http://unknown.example/v1", "insecure_http_confirmed_url": "http://unknown.example/v1", "private_endpoint_confirmed_url": "http://unknown.example/v1"})
            self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.db.get_automod_config(1), before)

    def test_private_confirmation_still_blocks_special_addresses_and_arbitrary_paths(self):
        for host in ("169.254.169.254", "0.0.0.0", "224.0.0.1", "240.0.0.1", "[fe80::1]", "[::]", "[ff02::1]", "[2001:db8::1]", "[fd00:ec2::254]"):
            url = f"http://{host}/v1"
            with self.subTest(host=host), self.assertRaises(ValueError):
                validate_llm_config({"endpoint_url": url, "insecure_http_confirmed_url": url, "private_endpoint_confirmed_url": url})
        for host in ("127.0.0.1", "10.1.2.3", "172.16.1.2", "192.168.1.20", "[::1]", "[fd00::123]"):
            url = f"http://{host}:8080/v1/"
            cfg = validate_llm_config({"endpoint_url": url, "insecure_http_confirmed_url": url, "private_endpoint_confirmed_url": url})
            self.assertEqual(cfg["private_endpoint_confirmed_url"], url)
        url = "http://127.0.0.1/admin/delete"
        with self.assertRaisesRegex(ValueError, "solo admite"):
            validate_llm_config({"endpoint_url": url, "insecure_http_confirmed_url": url, "private_endpoint_confirmed_url": url})

    async def test_shared_completion_and_auxiliary_transport_require_exact_consent(self):
        url = "http://model.example/v1"
        cfg = validate_llm_config({"endpoint_url": url, "insecure_http_confirmed_url": url, "model": "test"})
        answer = {"choices": [{"finish_reason": "stop", "message": {"content": "reply"}}]}
        async def chunks(size):
            yield json.dumps(answer).encode()
        class Response:
            status = 200
            content = SimpleNamespace(iter_chunked=chunks)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
        session = SimpleNamespace(post=Mock(return_value=Response()), get=Mock(return_value=Response()))
        self.assertEqual(await request_completion(session, cfg, []), "reply")
        self.assertEqual(session.post.call_args.args[0], "http://model.example/v1/chat/completions")
        self.assertEqual(await request_completion(session, cfg, [], moderation=True), "reply")
        self.assertIn("response_format", session.post.call_args.kwargs["json"])
        await endpoint_json(session, cfg, auxiliary="models")
        self.assertEqual(session.get.call_args.args[0], "http://model.example/v1/models")
        session.post.reset_mock()
        with self.assertRaisesRegex(ValueError, "http_confirmation"):
            await request_completion(session, {**cfg, "insecure_http_confirmed_url": ""}, [])
        session.post.assert_not_called()
        with self.assertRaisesRegex(ValueError, "private_address"):
            await request_completion(session, {**cfg, "endpoint_url": "http://127.0.0.1/v1", "insecure_http_confirmed_url": "http://127.0.0.1/v1"}, [])
        session.post.assert_not_called()

    async def test_private_dns_results_are_rejected_despite_http_consent(self):
        dns = SimpleNamespace(resolve=AsyncMock(return_value=[{"host": "10.1.2.3", "port": 80}]), close=AsyncMock())
        with patch("cogs._llm_moderation.aiohttp.resolver.DefaultResolver", return_value=dns):
            resolver = EndpointResolver()
            with self.assertRaisesRegex(OSError, "private_address"):
                await resolver.resolve("model.example", 80)
            await resolver.close()

    async def test_private_resolver_trust_is_exact_origin_and_never_allows_metadata(self):
        dns = SimpleNamespace(resolve=AsyncMock(return_value=[{"host": "10.1.2.3", "port": 8080}]), close=AsyncMock())
        with patch("cogs._llm_moderation.aiohttp.resolver.DefaultResolver", return_value=dns):
            resolver = EndpointResolver(private_origin=("model.local", 8080))
            self.assertEqual(await resolver.resolve("model.local", 8080), dns.resolve.return_value)
            for host, port in (("other.local", 8080), ("model.local", 8081)):
                with self.subTest(host=host, port=port), self.assertRaises(OSError):
                    await resolver.resolve(host, port)
            with self.assertRaises(OSError):
                await EndpointResolver().resolve("model.local", 8080)
            dns.resolve.return_value = [{"host": "169.254.169.254", "port": 8080}]
            with self.assertRaises(OSError):
                await resolver.resolve("model.local", 8080)
            dns.resolve.return_value = [{"host": "fd00:ec2::254", "port": 8080}]
            with self.assertRaises(OSError):
                await resolver.resolve("model.local", 8080)
            await resolver.close()

    async def test_private_transport_uses_closed_scoped_session_and_inherits_timeouts(self):
        url = "http://127.0.0.1:8080/v1"
        cfg = validate_llm_config({"endpoint_url": url, "insecure_http_confirmed_url": url, "private_endpoint_confirmed_url": url})
        shared = SimpleNamespace(timeout=aiohttp.ClientTimeout(total=6), post=Mock(), get=Mock())
        response_data = {"choices": [{"finish_reason": "stop", "message": {"content": "reply"}}]}
        cancelled = False
        async def chunks(size):
            if cancelled:
                raise asyncio.CancelledError
            yield json.dumps(response_data).encode()
        class Response:
            status = 200
            content = SimpleNamespace(iter_chunked=chunks)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
        class ScopedSession:
            def __init__(self):
                self.post, self.get = Mock(return_value=Response()), Mock(return_value=Response())
                self.closed = False
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                self.closed = True
        scoped = []
        def session(**kwargs):
            value = ScopedSession()
            scoped.append(value)
            return value
        dns = SimpleNamespace(resolve=AsyncMock(), close=AsyncMock())
        with patch("cogs._llm_moderation.aiohttp.resolver.DefaultResolver", return_value=dns), patch(
                "cogs._llm_moderation.aiohttp.TCPConnector") as connector, patch(
                "cogs._llm_moderation.aiohttp.ClientSession", side_effect=session) as factory:
            with self.assertRaises(ValueError):
                await endpoint_json(shared, {**cfg, "private_endpoint_confirmed_url": ""})
            factory.assert_not_called()
            self.assertEqual(await request_completion(shared, cfg, []), "reply")
            self.assertIs(factory.call_args.kwargs["timeout"], shared.timeout)
            self.assertFalse(factory.call_args.kwargs["trust_env"])
            self.assertFalse(connector.call_args.kwargs["use_dns_cache"])
            self.assertEqual(connector.call_args.kwargs["resolver"].private_origin, ("127.0.0.1", 8080))
            self.assertFalse(scoped[-1].post.call_args.kwargs["allow_redirects"])
            await endpoint_json(shared, cfg, auxiliary="models")
            self.assertEqual(scoped[-1].get.call_args.args[0], "http://127.0.0.1:8080/v1/models")
            self.assertEqual(scoped[-1].get.call_args.kwargs["timeout"].total, 8)
            await endpoint_json(shared, cfg, {}, auxiliary="messages/count_tokens")
            self.assertEqual(scoped[-1].post.call_args.args[0], "http://127.0.0.1:8080/v1/messages/count_tokens")
            cancelled = True
            with self.assertRaises(asyncio.CancelledError):
                await endpoint_json(shared, cfg)
            self.assertEqual(dns.close.await_count, 4)
        self.assertTrue(all(value.closed for value in scoped))
        shared.post.assert_not_called()
        shared.get.assert_not_called()

    async def test_two_save_flow_reaches_only_controlled_loopback_llm_fixture(self):
        received = []
        async def reply(reader, writer):
            try:
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head.decode("ascii").split("\r\n")
                headers = dict(line.split(": ", 1) for line in lines[1:] if ": " in line)
                body = await reader.readexactly(int(headers["Content-Length"]))
                received.append((lines[0], headers, json.loads(body)))
                data = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "respuesta del fixture local"}}]}).encode()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                             + str(len(data)).encode() + b"\r\nConnection: close\r\n\r\n" + data)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_server(reply, "127.0.0.1", 0)
        url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1"
        try:
            with self.assertRaises(HTTPException) as error:
                await self.save(1, {"endpoint_url": url, "model": "fixture-model"})
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(received, [])
            await self.save(1, {"endpoint_url": url, "model": "fixture-model", "api_key": "fixture-key",
                                "insecure_http_confirmed_url": url, "private_endpoint_confirmed_url": url})
            cfg = self.db.get_automod_config(1)["rules"]["llm"]
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as shared:
                answer = await request_completion(shared, cfg, [{"role": "user", "content": "prueba sintética"}])
            self.assertEqual(answer, "respuesta del fixture local")
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0][0], "POST /v1/chat/completions HTTP/1.1")
            self.assertEqual(received[0][1]["Authorization"], "Bearer fixture-key")
            self.assertEqual(received[0][2]["model"], "fixture-model")
        finally:
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
