import requests


def track_artist(track):
    return track.get("AlbumArtist") or (track.get("Artists") or [""])[0] or ""


class JellyfinClient:
    TIMEOUT = 15

    def __init__(self, server_url, api_key=None, username=None, password=None):
        self.server_url = server_url.rstrip("/")
        self.user_id = None
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"
        self.session.request = lambda method, url, **kw: requests.Session.request(
            self.session, method, url, timeout=kw.pop("timeout", self.TIMEOUT), **kw
        )
        # A password means the user is actively (re-)authenticating right
        # now - prefer that over a possibly stale/invalid stored api_key,
        # which would otherwise silently keep failing even after the user
        # corrects their credentials in Settings. Don't even send the old
        # api_key as a Token on the login request itself - an invalid/
        # expired one can make the server reject the whole request before
        # it looks at the username/password.
        if username and password:
            self.api_key = None
            self._set_auth_header()
            self._login(username, password)
        else:
            self.api_key = api_key
            if api_key:
                self.session.headers["X-MediaBrowser-Token"] = api_key
            self._set_auth_header()

    def _set_auth_header(self):
        # Jellyfin 10.11+ dropped the legacy X-Emby-Authorization header in
        # favor of the standard Authorization header with the MediaBrowser
        # scheme (optionally carrying the token too). Send both forms so
        # this keeps working against older Jellyfin servers as well.
        parts = [
            'Client="Jellyburn"',
            'Device="Linux"',
            'DeviceId="jellyburn-01"',
            'Version="1.0"',
        ]
        if self.api_key:
            parts.append(f'Token="{self.api_key}"')
        value = "MediaBrowser " + ", ".join(parts)
        self.session.headers["Authorization"] = value
        self.session.headers["X-Emby-Authorization"] = value

    def _login(self, username, password):
        url = f"{self.server_url}/Users/AuthenticateByName"
        # Strip stray CR/LF that can end up in the password when pasted
        # from a password manager or clipboard - modern Jellyfin's stricter
        # JSON parser rejects raw control characters in a JSON string with
        # a 400, where older servers tolerated them.
        username = username.replace("\r", "").replace("\n", "")
        password = password.replace("\r", "").replace("\n", "")
        resp = self.session.post(url, json={"Username": username, "Pw": password})
        resp.raise_for_status()
        data = resp.json()
        self.api_key = data["AccessToken"]
        self.user_id = data["User"]["Id"]
        self.session.headers["X-MediaBrowser-Token"] = self.api_key
        self._set_auth_header()

    def get_user_id(self):
        if self.user_id:
            return self.user_id
        resp = self.session.get(f"{self.server_url}/Users/Me")
        resp.raise_for_status()
        self.user_id = resp.json()["Id"]
        return self.user_id

    def search_music(self, query="", on_page=None):
        uid = self.get_user_id()
        params = {
            "IncludeItemTypes": "Audio",
            "Recursive": "true",
            "Fields": "RunTimeTicks,AlbumArtist,Album,Path,ParentId,ArtistIds",
            "UserId": uid,
            "Limit": 500,
            "StartIndex": 0,
        }
        if query:
            params["SearchTerm"] = query
            resp = self.session.get(f"{self.server_url}/Items", params=params)
            resp.raise_for_status()
            return resp.json().get("Items", [])

        all_items = []
        total = None
        while True:
            params["StartIndex"] = len(all_items)
            resp = self.session.get(f"{self.server_url}/Items", params=params)
            resp.raise_for_status()
            data = resp.json()
            if total is None:
                total = data.get("TotalRecordCount", 0)
            page = data.get("Items", [])
            all_items.extend(page)
            if on_page:
                on_page(page, len(all_items), total)
            if len(all_items) >= total or not page:
                break
        return all_items

    def get_stream_url(self, item_id):
        uid = self.get_user_id()
        return (
            f"{self.server_url}/Audio/{item_id}/stream"
            f"?UserId={uid}&api_key={self.api_key}&AudioCodec=flac&Container=flac"
        )

    def get_download_url(self, item_id):
        return f"{self.server_url}/Items/{item_id}/Download?api_key={self.api_key}"

    def ticks_to_seconds(self, ticks):
        return ticks // 10_000_000 if ticks else 0

    def format_duration(self, ticks):
        s = self.ticks_to_seconds(ticks)
        return f"{s // 60}:{s % 60:02d}"
