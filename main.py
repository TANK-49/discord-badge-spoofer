from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterator, Sequence

import aiohttp
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"

GATEWAY_URL = "wss://gateway.discord.gg/?v=9&encoding=json"
SCIENCE_URL = "https://discord.com/api/v9/science"
GAMES_CDN_URL = "https://cdn.discordapp.com/detectables/games.json" 

BATCH_SIZE = 50
BATCH_DELAY = 0.3
AUTH_MAX_AGE = 12 * 3600

CLIENT_VERSION = "1.0.9253"
CLIENT_BUILD_NUMBER = 594031
NATIVE_BUILD_NUMBER = 88414
OS_VERSION = "10.0.26200"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) discord/1.0.9253 Chrome/148.0.7778.280 "
    "Electron/42.7.1 Safari/537.36"
)


class Console:
    """colored console output."""

    RED = "\x1b[91m"
    ORANGE = "\x1b[38;5;208m"
    GREEN = "\x1b[92m"
    YELLOW = "\x1b[93m"
    WHITE = "\x1b[97m"
    GREY = "\x1b[90m"
    RESET = "\x1b[0m"
    RULE = "─" * 60

    def __init__(self) -> None:
        if sys.platform == "win32":
            try:
                self._enable_ansi()
            except Exception:
                pass

    @staticmethod
    def _enable_ansi() -> None:
        try:
            import ctypes
            if hasattr(ctypes, "windll"):
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.GetStdHandle(-11)
                if handle is not None:
                    mode = ctypes.c_uint32()
                    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass

    def _stamp(self) -> str:
        return f"{self.GREY}{time.strftime('%H:%M:%S')}{self.RESET}"

    def _line(self, glyph: str, eng: str, ara: str, color: str) -> None:
        print(f"  {self._stamp()} {glyph} {self.WHITE}{eng}{self.RESET} "
              f"{self.GREY}|{self.RESET} {color}{ara}{self.RESET}")

    def ok(self, eng: str, ara: str) -> None:
        self._line(f"{self.GREEN}✓{self.RESET}", eng, ara, self.GREEN)

    def warn(self, eng: str, ara: str) -> None:
        self._line(f"{self.YELLOW}!{self.RESET}", eng, ara, self.YELLOW)

    def err(self, eng: str, ara: str) -> None:
        self._line(f"{self.RED}✗{self.RESET}", eng, ara, self.RED)

    def info(self, eng: str, ara: str) -> None:
        print(f"  {self._stamp()} {self.GREY}·{self.RESET} {self.WHITE}{eng}{self.RESET} "
              f"{self.GREY}|{self.RESET} {self.WHITE}{ara}{self.RESET}")

    def err_str(self, eng: str, ara: str) -> str:
        return f"{self.RED}✗{self.RESET} {self.WHITE}{eng}{self.RESET} {self.GREY}|{self.RESET} {self.RED}{ara}{self.RESET}"

    def warn_str(self, eng: str, ara: str) -> str:
        return f"{self.YELLOW}!{self.RESET} {self.WHITE}{eng}{self.RESET} {self.GREY}|{self.RESET} {self.YELLOW}{ara}{self.RESET}"

    def prompt(self, eng: str, ara: str, mask: bool = False) -> str:
        prompt_str = f"  {self.ORANGE}›{self.RESET} {self.WHITE}{eng}{self.RESET} {self.GREY}|{self.RESET} {self.WHITE}{ara}{self.RESET}: "
        val = input(prompt_str).strip()
        if mask and val:
            print("\x1b[1A\x1b[2K", end="")
            if len(val) <= 12:
                masked_val = "*" * len(val)
            else:
                masked_val = f"{val[:6]}...{val[-6:]}"
            print(f"{prompt_str}{self.GREY}{masked_val}{self.RESET}")
        return val

    def rule(self) -> None:
        print(f"  {self.GREY}{self.RULE}{self.RESET}")

    def clear(self) -> None:
        print("\x1b[2J\x1b[3J\x1b[H", end="")

    def banner(self) -> None:
        self.clear()
        print()
        print(f"    {self.GREY}Email | el-barid: {self.WHITE}ask@tank49.tech{self.RESET}")
        print(f"    {self.GREY}Discord | discord: {self.WHITE}discord.gg/pepo{self.RESET}")
        print()


@dataclass
class State:
    """saved auth. token + cookie are yours to supply, the rest is auto."""

    token: str = ""
    cookie: str = ""
    fingerprint: str = ""
    analytics_token: str = ""
    super_props: str = ""
    heartbeat_session: str = ""
    launch_signature: str = ""
    fetched_at: int = 0

    @classmethod
    def load(cls) -> "State":
        if ENV_FILE.exists():
            env = {}
            try:
                for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip().lower()] = v.strip()
                
                return cls(
                    token=env.get("discord_token", env.get("token", "")),
                    cookie=env.get("discord_cookie", env.get("cookie", "")),
                    fingerprint=env.get("discord_fingerprint", env.get("fingerprint", "")),
                    analytics_token=env.get("analytics_token", ""),
                    super_props=env.get("super_props", ""),
                    heartbeat_session=env.get("heartbeat_session", ""),
                    launch_signature=env.get("launch_signature", ""),
                    fetched_at=int(env.get("fetched_at", "0"))
                )
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        try:
            lines = [
                f"DISCORD_TOKEN={self.token}",
                f"DISCORD_COOKIE={self.cookie}",
                f"DISCORD_FINGERPRINT={self.fingerprint}",
                f"ANALYTICS_TOKEN={self.analytics_token}",
                f"SUPER_PROPS={self.super_props}",
                f"HEARTBEAT_SESSION={self.heartbeat_session}",
                f"LAUNCH_SIGNATURE={self.launch_signature}",
                f"FETCHED_AT={self.fetched_at}"
            ]
            ENV_FILE.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass

    @property
    def is_stale(self) -> bool:
        return not self.analytics_token or (time.time() - self.fetched_at) > AUTH_MAX_AGE

    @property
    def has_cookie(self) -> bool:
        return bool(self.cookie.strip())

    @property
    def has_token(self) -> bool:
        return bool(self.token.strip())


def build_super_props(launch_signature: str, heartbeat_session: str) -> str:
    props = {
        "os": "Windows",
        "browser": "Discord Client",
        "release_channel": "stable",
        "client_version": CLIENT_VERSION,
        "os_version": OS_VERSION,
        "os_arch": "x64",
        "app_arch": "x64",
        "system_locale": "en-GB",
        "has_client_mods": False,
        "client_launch_id": str(uuid.uuid4()),
        "browser_user_agent": USER_AGENT,
        "browser_version": "42.7.1",
        "os_sdk_version": "26200",
        "client_build_number": CLIENT_BUILD_NUMBER,
        "native_build_number": NATIVE_BUILD_NUMBER,
        "client_event_source": None,
        "launch_signature": launch_signature,
        "client_heartbeat_session_id": heartbeat_session,
        "client_app_state": "focused",
    }
    raw = json.dumps(props, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


async def _read_analytics_token(auth_token: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(GATEWAY_URL, max_msg_size=0) as ws:
            await ws.receive_json()
            await ws.send_json({
                "op": 2,
                "d": {
                    "token": auth_token,
                    "capabilities": 30717,
                    "properties": {
                        "os": "Windows",
                        "browser": "Discord Client",
                        "release_channel": "stable",
                        "client_version": CLIENT_VERSION,
                        "os_version": OS_VERSION,
                        "system_locale": "en-GB",
                    },
                },
            })
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                if data.get("op") == 9:
                    raise RuntimeError("gateway rejected token (invalid session)")
                if data.get("t") == "READY":
                    token = data["d"].get("analytics_token")
                    if not token:
                        raise RuntimeError("READY payload had no analytics_token")
                    return token
    raise RuntimeError("gateway closed before READY")


def refresh_auth(state: State) -> None:
    """grab a fresh analytics token and rebuild the bundle. leaves token + cookie alone."""
    analytics_token = asyncio.run(_read_analytics_token(state.token))
    state.analytics_token = analytics_token
    state.heartbeat_session = str(uuid.uuid4())
    state.launch_signature = str(uuid.uuid4())
    state.super_props = build_super_props(state.launch_signature, state.heartbeat_session)
    state.fetched_at = int(time.time())
    state.save()


@dataclass(frozen=True)
class Game:
    id: str
    name: str
    exe: str


def _win_exe(game: dict) -> str:
    for entry in game.get("executables", []):
        if entry.get("os") == "win32" and entry.get("name"):
            return entry["name"]
    return "game.exe"


def _download_games() -> str:
    request = urllib.request.Request(GAMES_CDN_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def load_games() -> list[Game]:
    try:
        raw = _download_games()
    except Exception:
        return []
    data = json.loads(raw)
    games: list[Game] = []
    seen: set[str] = set()
    for entry in data:
        gid = str(entry.get("id", ""))
        if not gid.isdigit() or gid in seen:
            continue
        if not any(e.get("os") == "win32" and e.get("name") for e in entry.get("executables", [])):
            continue
        seen.add(gid)
        games.append(Game(gid, entry.get("name", "Unknown"), _win_exe(entry)))
    return games


class ScienceClient:
    """builds and posts launch_game and running_game_heartbeat events."""

    def __init__(self, state: State) -> None:
        self.state = state
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def build_launch(self, game: Game) -> dict:
        now = int(time.time() * 1000)
        props = {
            "client_track_timestamp": now,
            "client_heartbeat_session_id": self.state.heartbeat_session,
            "event_sequence_number": self._next_seq(),
            "game": game.name,
            "game_id": game.id,
            "verified": True,
            "elevated": False,
            "is_launcher": False,
            "game_platform": "desktop",
            "detection_method": "verified_game",
            "is_overlay_enabled": False,
            "is_overlay_game_enabled": True,
            "is_overlay_game_source": "OOP_DEFAULT_DATABASE",
            "fullscreen_type": "UNKNOWN",
            "hardware_display_count": 1,
            "overlay_method": "Disabled",
            "activity_status_enabled": True,
            "activity_status_shared_guilds": [],
            "current_user_status": "online",
            "game_detection_enabled": True,
            "executable_path": game.exe,
            "voice_channel_id": None,
            "voice_channel_type": None,
            "voice_channel_bitrate": None,
            "voice_channel_guild_id": None,
            "hidden_by_distributor": False,
            "game_metadata": None,
            "executable_fingerprint": self.state.fingerprint,
            "client_performance_cpu": None,
            "client_performance_memory": None,
            "cpu_core_count": None,
            "accessibility_features": 0,
            "rendered_locale": "en-GB",
            "launch_signature": self.state.launch_signature,
            "client_rtc_state": None,
            "client_app_state": "focused",
            "client_send_timestamp": now,
        }
        if not self.state.fingerprint:
            del props["executable_fingerprint"]
        return {"type": "launch_game", "properties": props}

    def build_heartbeat(self, game: Game, duration_ms: int, session_id: str,
                        initial: bool, final: bool, ts: int | None = None) -> dict:
        ts = int(time.time() * 1000) if ts is None else ts
        return {
            "type": "running_game_heartbeat",
            "properties": {
                "client_track_timestamp": ts,
                "client_heartbeat_session_id": self.state.heartbeat_session,
                "event_sequence_number": self._next_seq(),
                "game_id": game.id,
                "game_name": game.name,
                "game_metadata": None,
                "game_executable": game.exe,
                "game_detection_enabled": True,
                "initial_heartbeat": initial,
                "final_heartbeat": final,
                "game_session_id": session_id,
                "duration_tracked_ms": duration_ms,
                "rtc_connection_id": None,
                "media_session_id": None,
                "launch_signature": self.state.launch_signature,
                "client_app_state": "focused",
                "client_send_timestamp": ts,
            },
        }

    def build_session(self, game: Game, duration_ms: int) -> list[dict]:
        sid = str(uuid.uuid4())
        now = int(time.time() * 1000)
        start = now - duration_ms
        if start < 0:
            start = now
        return [
            self.build_heartbeat(game, 0, sid, initial=True, final=False, ts=start),
            self.build_launch(game),
            self.build_heartbeat(game, duration_ms, sid, initial=False, final=True, ts=now),
        ]

    def post(self, events: Sequence[dict]) -> int:
        """post a batch. returns the http status (204 = accepted)."""
        body = json.dumps({"token": self.state.analytics_token, "events": list(events)}).encode("utf-8")
        request = urllib.request.Request(SCIENCE_URL, data=body, method="POST", headers={
            "accept": "*/*",
            "accept-language": "en-GB",
            "authorization": self.state.token,
            "content-type": "application/json",
            "cookie": self.state.cookie,
            "origin": "https://discord.com",
            "referer": "https://discord.com/channels/@me",
            "user-agent": USER_AGENT,
            "x-debug-options": "bugReporterEnabled",
            "x-discord-locale": "en-GB",
            "x-discord-timezone": "Europe/Oslo",
            "x-super-properties": self.state.super_props,
        })
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except Exception:
            return 0


def _chunked(items: Sequence[Game], size: int) -> Iterator[Sequence[Game]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


class Spoofer:
    """sends events in batches and logs progress."""

    def __init__(self, client: ScienceClient, console: Console) -> None:
        self.client = client
        self.console = console

    def run(self, games: Sequence[Game], build_events) -> int:
        total = len(games)
        sent_ok = 0
        desc = "Progress | el-taqadom"
        
        with tqdm(total=total, desc=desc, unit="game", bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]") as pbar:
            for request_no, chunk in enumerate(_chunked(games, BATCH_SIZE), start=1):
                events = []
                for game in chunk:
                    events.extend(build_events(game))
                status = self.client.post(events)
                if status == 204:
                    sent_ok += len(chunk)
                    pbar.update(len(chunk))
                elif status in (401, 403):
                    pbar.write(f"  {self.console.err_str('Auth rejected · refresh with fresh cookie', 'el-auth etrafa2 · geded b-cookie gedid')} [{status}]")
                    return sent_ok
                else:
                    pbar.write(f"  {self.console.warn_str(f'Batch {request_no} failed', f'fashalet el-daf3a {request_no}')} [{status}]")
                time.sleep(BATCH_DELAY)
        return sent_ok


class App:
    def __init__(self) -> None:
        self.console = Console()
        self.state = State.load()
        self.games: list[Game] = []

    def start(self) -> None:

        self.console.banner()

        if not self.state.has_token or not self.state.has_cookie:
            self.console.info(
                "Need help? View the complete guide here:",
                "3ayz mosa3da? shof el-shar7 el-kamel hena:"
            )
            print(f"  {self.console.ORANGE}➔     https://tank49.tech/blog/discord-badge-spoofer{self.console.RESET}\n")

        if not self.state.has_token:
            entered = self.console.prompt("Enter Discord Token", "ed5ol token discord", mask=True)
            if not entered:
                self.console.err("Token is required to continue", "el-token matloob lel-motaba3a")
                return
            self.state.token = entered
            self.state.save()
            self.console.ok("Token saved", "tm 7afz el-token")
        else:
            self.console.info(
                "Saved token found. Press Enter to keep it, or paste a new one.",
                "Le2ena token ma7foo2. Dos Enter 3ashan tekamel beh, aw 7ot wa7ed gedid."
            )
            entered = self.console.prompt("Token (press Enter to keep)", "el-token (dos Enter lel-2eb2a2)", mask=True)
            if entered:
                self.state.token = entered
                self.state.save()
                self.console.ok("Token updated", "tm ta7deeth el-token")

        if not self.state.has_cookie:
            entered = self.console.prompt("Enter Cookie (cf_clearance)", "ed5ol cookie (cf_clearance)", mask=True)
            if not entered:
                self.console.err("Cookie is required to continue", "el-cookie matloob lel-motaba3a")
                return
            self.state.cookie = entered
            self.state.save()
            self.console.ok("Cookie saved", "tm 7afz el-cookie")
        else:
            self.console.info(
                "Saved cookie found. Press Enter to keep it, or paste a new one.",
                "Le2ena cookie ma7foo2. Dos Enter 3ashan tekamel beh, aw 7ot wa7ed gedid."
            )
            entered = self.console.prompt("Cookie (press Enter to keep)", "el-cookie (dos Enter lel-2eb2a2)", mask=True)
            if entered:
                self.state.cookie = entered
                self.state.save()
                self.console.ok("Cookie updated", "tm ta7deeth el-cookie")

        self.games = load_games()
        if not self.games:
            self.console.err(
                "Failed to download games database from Discord CDN",
                "fashal ta7meel database el-el3ab men Discord CDN"
            )
            return
        if len(self.games) >= 100:
            self.console.ok(
                "Tool is ready to run",
                "el-ada shagala w gahza"
            )
        else:
            self.console.warn(
                f"Only {len(self.games)} games found",
                f"fi {len(self.games)} le3ba bas"
            )

        if self.state.is_stale:
            self.console.info("Preparing connection...", "ben-gahz el-etisal...")
            try:
                refresh_auth(self.state)
            except Exception as exc:
                self.console.err(
                    f"Gateway connection failed: {exc}",
                    f"fashal el-etisal bel-gateway: {exc}"
                )
                return
        self.console.rule()
        self.console.info("Choose Mode | e5tar el-mode", "e5tar el-amalya elly 3ayz ta3melha")
        print(f"  {self.console.ORANGE}1{self.console.RESET} {self.console.WHITE}🎮 Game Diversity (+100 games) {self.console.GREY}|{self.console.WHITE} tanowwo3 el-el3ab (+100 le3ba){self.console.RESET}")
        print(f"  {self.console.ORANGE}2{self.console.RESET} {self.console.WHITE}🗡️ Game Depth (+5000 hours) {self.console.GREY}|{self.console.WHITE} sa3at el-la3b (+5000 sa3a){self.console.RESET}")
        self.console.rule()

        choice = ""
        while choice not in ("1", "2"):
            choice = self.console.prompt("Enter choice (1 or 2)", "ed5ol e5tyarak (1 aw 2)")

        if choice == "1":
            self.module_game_variety()
            self.console.rule()
            other = ""
            while other not in ("y", "n"):
                other = self.console.prompt("Do you want to claim 🗡️ Game Depth now? (y/n)", "3ayz te3mel sa3at el-la3b kaman? (y/n)").lower()
            if other == "y":
                self.module_game_time()
        elif choice == "2":
            self.module_game_time()
            self.console.rule()
            other = ""
            while other not in ("y", "n"):
                other = self.console.prompt("Do you want to claim 🎮 Game Diversity now? (y/n)", "3ayz te3mel tanowwo3 el-el3ab kaman? (y/n)").lower()
            if other == "y":
                self.module_game_variety()

    def module_game_variety(self) -> None:
        games_to_run = self.games[:115]
        if len(games_to_run) < 115:
            self.console.warn(
                f"Only {len(games_to_run)} games available in database",
                f"fi {len(games_to_run)} le3ba bas fel-database"
            )
        self.console.info(
            f"Claiming {len(games_to_run)} unique games (1m duration each)",
            f"benmtaleb b {len(games_to_run)} le3ba farida (maddet da2i2a le-kol wa7da)"
        )
        self.console.rule()
        client = ScienceClient(self.state)
        ok = Spoofer(client, self.console).run(
            games_to_run,
            lambda g: client.build_session(g, 60 * 1000),
        )
        self.console.rule()
        self.console.ok(
            f"Complete: {ok}/{len(games_to_run)} games marked played",
            f"5alas: tm tasgiel {ok}/{len(games_to_run)} le3ba enaha etla3bet"
        )

    def module_game_time(self) -> None:
        games_to_run = self.games[:6]
        games_count = len(games_to_run)
        if games_count == 0:
            return
        hours = (5755 + games_count - 1) // games_count
        duration_ms = int(hours * 3600 * 1000)
        self.console.info(
            f"Claiming {hours}h on {games_count} games (total {games_count * hours:,.0f}h)",
            f"benmtaleb b {hours} sa3a 3la {games_count} le3ba (el-gomla {games_count * hours:,.0f} sa3a)"
        )
        self.console.rule()
        client = ScienceClient(self.state)
        ok = Spoofer(client, self.console).run(
            games_to_run,
            lambda g: client.build_session(g, duration_ms),
        )
        self.console.rule()
        self.console.ok(
            f"Complete: {ok}/{games_count} games · {ok * hours:,.0f}h claimed",
            f"5alas: {ok}/{games_count} le3ba · tm tasgiel {ok * hours:,.0f} sa3a"
        )


def main() -> None:
    try:
        App().start()
    except KeyboardInterrupt:
        print()
        Console().warn("Exit: Interrupted", "5roog: tm el-mo2ata3a")


if __name__ == "__main__":
    main()
