"""An in-memory Moodle web service for tests."""

import io
import json
import urllib.error
import urllib.parse

TOKEN = "secret-test-token"


class FakeMoodle:
    def __init__(self):
        self.courses: dict[int, list[dict]] = {}
        self.blobs: dict[str, bytes] = {}
        self.down: set[int] = set()
        self.downloads: list[str] = []

    def add_file(self, course_id, filename, content, timemodified=1000):
        url = f"https://moodle.test/webservice/pluginfile.php/{course_id}/{filename}"
        self.blobs[url] = content
        files = self.courses.setdefault(course_id, [])
        files[:] = [f for f in files if f["fileurl"] != url]
        files.append(
            {"type": "file", "filename": filename, "fileurl": url, "timemodified": timemodified, "filesize": len(content)}
        )

    def __call__(self, url):
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        if parsed.path.endswith("/webservice/rest/server.php"):
            if query.get("wstoken") != TOKEN:
                return io.BytesIO(json.dumps({"exception": "x", "errorcode": "invalidtoken", "message": "Invalid token"}).encode())
            course_id = int(query["courseid"])
            if course_id in self.down:
                raise urllib.error.URLError("down")
            modules = [{"contents": [f]} for f in self.courses.get(course_id, [])]
            modules.append({"contents": [{"type": "url", "filename": "link", "fileurl": "https://x"}]})
            return io.BytesIO(json.dumps([{"modules": modules}]).encode())
        base = url.split("?")[0]
        self.downloads.append(base)
        return io.BytesIO(self.blobs[base])
