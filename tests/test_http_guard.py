import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer

import server  # noqa: F401  (loads first; http_handler imports back into it)
import http_handler


class LocalNameTest(unittest.TestCase):
    def test_local_names(self):
        for v in ("127.0.0.1:8000", "localhost", "LOCALHOST:8123", "[::1]:8000",
                  "http://127.0.0.1:8000", "http://localhost:8000/"):
            self.assertTrue(http_handler.Handler._local_host(v), v)

    def test_foreign_names(self):
        for v in ("evil.example", "evil.example:8000", "127.0.0.1.evil.example",
                  "http://evil.example", "localhost.evil.example:8000"):
            self.assertFalse(http_handler.Handler._local_host(v), v)


class LiveGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), http_handler.Handler)
        cls.srv.daemon_threads = True
        cls.port = cls.srv.server_port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path, headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        try:
            r.read()
        except ConnectionResetError:
            # A request refused before its body is read is closed at once;
            # the status line has already arrived.
            pass
        out = (r.status, r.getheader("X-Content-Type-Options"))
        c.close()
        return out

    def test_own_page_served_with_nosniff(self):
        self.assertEqual(self.req("GET", "/static/app.css"), (200, "nosniff"))

    def test_foreign_host_refused(self):
        self.assertEqual(self.req("GET", "/static/app.css", {"Host": "evil.example"}),
                         (404, None))

    def test_foreign_origin_post_refused(self):
        # Refused before the body is read, so nothing is recorded.
        status, _ = self.req("POST", "/api/watch", {"Origin": "https://evil.example",
                                                    "Content-Type": "text/plain"}, "[]")
        self.assertEqual(status, 404)

    def test_dot_dot_out_of_static_refused(self):
        # translate_path folds ".." away, so a prefix check alone let these out.
        for p in ("/static/../server.py", "/static/%2e%2e/server.py",
                  "/static/..%2fserver.py", "/static/../CLAUDE.md"):
            self.assertEqual(self.req("GET", p)[0], 404, p)

    def test_negative_length_does_not_hang(self):
        status, _ = self.req("POST", "/api/watch", {"Content-Length": "-1"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
