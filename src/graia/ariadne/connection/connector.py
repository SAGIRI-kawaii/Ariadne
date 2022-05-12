import abc
import asyncio
import secrets
from typing import Any, Callable, Dict, Generic, MutableMapping, Optional, Set, Type
from weakref import WeakValueDictionary

from aiohttp import FormData
from graia.amnesia.builtins.aiohttp import AiohttpClientInterface
from graia.amnesia.json import Json
from graia.amnesia.launch.manager import LaunchManager
from graia.amnesia.transport import Transport
from graia.amnesia.transport.common.http import AbstractServerRequestIO, HttpEndpoint
from graia.amnesia.transport.common.http.extra import HttpRequest
from graia.amnesia.transport.common.status import (
    ConnectionStatus as BaseConnectionStatus,
)
from graia.amnesia.transport.common.websocket import (
    AbstractWebsocketIO,
    WebsocketCloseEvent,
    WebsocketConnectEvent,
    WebsocketEndpoint,
    WebsocketReceivedEvent,
    WSConnectionAccept,
    WSConnectionClose,
)
from graia.amnesia.transport.common.websocket.shortcut import data_type, json_require
from graia.amnesia.transport.utilles import TransportRegistrar
from loguru import logger
from yarl import URL

from graia.ariadne.exception import InvalidSession

from .config import (
    ConfigUnion,
    HttpClientConfig,
    HttpServerConfig,
    T_Config,
    WebsocketClientConfig,
    WebsocketServerConfig,
)
from .util import CallMethod, build_event, get_router, validate_response


class ConnectionStatus(BaseConnectionStatus):
    def __init__(self) -> None:
        self.session_key: Optional[str] = None
        self.succeed: Optional[bool] = None
        self.connected: bool = False
        super().__init__("elizabeth.connection")

    def update(
        self,
        session_key: Optional[str] = ...,
        connected: Optional[bool] = None,
        succeed: Optional[bool] = None,
    ):
        past = self.frame
        if session_key is not ...:
            self.session_key = session_key
            self.connected = session_key is not None
        if connected is not None:
            self.connected = connected
        if succeed is not None:
            self.succeed = succeed
        self.notify(past)

    @property
    def available(self) -> bool:
        return bool(self.connected and self.session_key)


class AbstractConnector(Generic[T_Config]):
    status: ConnectionStatus
    config: T_Config
    dependency: Set[str]
    http_interface: AiohttpClientInterface

    def __init__(self, config: T_Config) -> None:
        self.config = config
        self.status = ConnectionStatus()

    @abc.abstractmethod
    async def mainline(self, mgr: LaunchManager) -> None:
        ...

    async def call(self, method: CallMethod, command: str, params: Optional[dict] = None) -> Any:
        raise NotImplementedError(
            f"Connector {self} can't perform {command!r}, consider *hooking* a HttpClientConnector?"
        )


_reg = TransportRegistrar()


@_reg.apply
class AbstractWebsocketConnector(Transport):
    ws_io: AbstractWebsocketIO
    futures: MutableMapping[str, asyncio.Future]
    status: ConnectionStatus

    @_reg.on(WebsocketReceivedEvent)
    @data_type(str)
    @json_require
    async def _(self, io: AbstractWebsocketIO, raw: Any) -> None:  # event pass and callback
        assert isinstance(raw, dict)
        if "code" in raw:  # something went wrong
            validate_response(raw)  # raise it
        sync_id: str = raw.get("syncId", "#")
        data = raw.get("data", None)
        data = validate_response(data)
        if "session" in data:
            self.status.update(session_key=data["session"])
            logger.success("Successfully got session key", style="green bold")
            return
        if sync_id in self.futures:
            self.futures[sync_id].set_result(data)
        elif "type" in data:
            logger.debug(build_event(data))  # TODO: broadcast
        else:
            logger.warning(f"Got unknown data: {data}")

    @_reg.on(WebsocketCloseEvent)
    async def _(self, _: AbstractWebsocketIO) -> None:
        del self.ws_io
        self.status.update(session_key=None)

    async def call(self, method: CallMethod, command: str, params: Optional[dict] = None) -> Any:
        params = params or {}
        sync_id: str = secrets.token_urlsafe(12)
        fut = asyncio.get_running_loop().create_future()
        content: Dict[str, Any] = {"syncId": sync_id, "command": command, "content": params or {}}
        if method == CallMethod.RESTGET:
            content["subCommand"] = "get"
        elif method == CallMethod.RESTPOST:
            content["subCommand"] = "update"
        elif method == CallMethod.MULTIPART:
            raise NotImplementedError("Please hook HttpClientConnector for multipart operation")
        self.futures[sync_id] = fut
        await self.status.wait_for_available()
        await self.ws_io.send(content)
        return await fut


_reg = TransportRegistrar()


@_reg.apply
class WebsocketServerConnector(AbstractWebsocketConnector, AbstractConnector[WebsocketServerConfig]):
    dependency = {"http.universal_server"}

    def __init__(self, config: WebsocketServerConfig) -> None:
        AbstractConnector.__init__(self, config)
        self.declares.append(WebsocketEndpoint(self.config.path))
        self.futures = WeakValueDictionary()

    async def mainline(self, mgr: LaunchManager) -> None:
        self.http_interface = mgr.get_interface(AiohttpClientInterface)
        router = get_router(mgr)
        router.use(self)

    @_reg.on(WebsocketConnectEvent)
    async def _(self, io: AbstractWebsocketIO) -> None:
        req: HttpRequest = await io.extra(HttpRequest)
        for k, v in self.config.headers:
            if req.headers.get(k) != v:
                return await io.extra(WSConnectionClose)
        for k, v in self.config.params:
            if req.query_params.get(k) != v:
                return await io.extra(WSConnectionClose)
        await io.extra(WSConnectionAccept)
        logger.info("WebsocketServer")
        await io.send(
            {
                "syncId": "#",
                "command": "verify",
                "content": {
                    "verifyKey": self.config.verify_key,
                    "sessionKey": None,
                    "qq": self.config.account,
                },
            }
        )
        self.ws_io = io


_reg = TransportRegistrar()


@_reg.apply
class WebsocketClientConnector(AbstractWebsocketConnector, AbstractConnector[WebsocketClientConfig]):
    dependency = {"http.universal_client"}

    def __init__(self, config: WebsocketClientConfig) -> None:
        AbstractConnector.__init__(self, config)
        self.futures = WeakValueDictionary()

    async def mainline(self, mgr: LaunchManager) -> None:
        config = self.config
        self.http_interface = mgr.get_interface(AiohttpClientInterface)
        await self.http_interface.websocket(
            str((URL(config.host) / "all").with_query({"qq": config.account, "verifyKey": config.verify_key}))
        ).use(self)

    @_reg.on(WebsocketConnectEvent)
    async def _(self, io: AbstractWebsocketIO) -> None:  # start authenticate
        self.ws_io = io


class HttpServerConnector(AbstractConnector[HttpServerConfig], Transport):
    dependency = {"http.universal_server"}

    def __init__(self, config: HttpServerConfig) -> None:
        super().__init__(config)
        self.handlers[HttpEndpoint(self.config.path, ["POST"])] = self.__class__.handle_request

    async def handle_request(self, io: AbstractServerRequestIO):
        req: HttpRequest = await io.extra(HttpRequest)
        if req.headers.get("qq") != str(self.config.account):
            return
        for k, v in self.config.headers:
            if req.headers.get(k) != v:
                return "Authorization failed", {"status": 401}
        data = Json.deserialize((await io.read()).decode("utf-8"))
        assert isinstance(data, dict)
        self.status.update(connected=True)
        logger.debug(build_event(data))  # TODO: broadcast
        return {"command": "", "data": {}}

    async def mainline(self, mgr: LaunchManager) -> None:
        self.http_interface = mgr.get_interface(AiohttpClientInterface)
        router = get_router(mgr)
        router.use(self)


class HttpClientConnector(AbstractConnector[HttpClientConfig]):
    dependency = {"http.universal_client"}
    http_interface: AiohttpClientInterface

    def __init__(self, config: HttpClientConfig) -> None:
        AbstractConnector.__init__(self, config)
        self.interface_getter: Callable[[], AiohttpClientInterface] = lambda: self.http_interface

    async def request(
        self,
        method: str,
        url: str,
        params: Optional[dict] = None,
        data: Optional[Any] = None,
        json: Optional[dict] = None,
    ) -> Any:
        if data and isinstance(data, dict):
            form = FormData(quote_fields=False)
            for k, v in data.values():
                form.add_field(k, **v)
            data = form
        rider = await self.interface_getter().request(method, url, params=params, data=data, json=json)
        byte_data = await rider.io().read()
        result = Json.deserialize(byte_data.decode("utf-8"))
        return validate_response(result)

    async def http_auth(self) -> None:
        data = await self.request(
            "POST",
            self.config.get_url("verify"),
            json={"verifyKey": self.config.verify_key},
        )
        session_key = data["session"]
        await self.request(
            "POST",
            self.config.get_url("bind"),
            json={"qq": self.config.account, "sessionKey": session_key},
        )
        self.status.update(session_key=session_key)

    async def call(self, method: CallMethod, command: str, params: Optional[dict] = None) -> Any:
        params = params or {}
        command = command.replace("_", "/")
        while not self.status.connected:
            await self.status.wait_for_update()
            logger.debug("Got update")
        if not self.status.session_key:
            await self.http_auth()
        try:
            if method in (CallMethod.GET, CallMethod.RESTGET):
                return await self.request("GET", self.config.get_url(command), params=params)
            elif method in (CallMethod.POST, CallMethod.RESTPOST):
                return await self.request("POST", self.config.get_url(command), json=params)
            elif method == CallMethod.MULTIPART:
                return await self.request("POST", self.config.get_url(command), data=params)
        except InvalidSession:
            self.status.update(session_key=None)
            raise

    async def mainline(self, mgr: LaunchManager) -> None:
        self.http_interface = mgr.get_interface(AiohttpClientInterface)
        try:
            await self.http_auth()
        except Exception as e:
            self.status.update(session_key=None)
            logger.exception(e)
        else:
            self.status.update(succeed=True)
            while self.status.connected:
                await asyncio.sleep(0.5)
                data = await self.request(
                    "GET",
                    self.config.get_url("fetchMessage"),
                    {"sessionKey": self.status.session_key, "count": 10},
                )
                assert isinstance(data, list)
                for event_data in data:
                    logger.debug(build_event(event_data))  # TODO: broadcast

    def hook(self, connector: AbstractConnector):
        self.interface_getter = lambda: connector.http_interface
        self.status = connector.status
        connector.call = self.call


CONFIG_MAP: Dict[Type[ConfigUnion], Type[AbstractConnector]] = {
    HttpClientConfig: HttpClientConnector,
    HttpServerConfig: HttpServerConnector,
    WebsocketClientConfig: WebsocketClientConnector,
    WebsocketServerConfig: WebsocketServerConnector,
}
