import asyncio
import os
import re
from typing import Optional, Union

import devtools
from graia.amnesia import log
from graia.broadcast import Broadcast
from graia.broadcast.builtin.event import ExceptionThrowed
from loguru import logger

from graia.ariadne.entry import *

log.install()
if __name__ == "__main__":
    url, account, verify_key, target, t_group = (
        open(os.path.join(__file__, "..", "test.temp"), "r").read().split(" ")
    )
    ALL_FLAG = True
    Ariadne.service.loop.set_debug(True)

    app = Ariadne(
        [
            WebsocketClientConfig(account=account, verify_key=verify_key, module_check=False),
            HttpClientConfig(account=account, verify_key=verify_key, module_check=False),
        ]
    )

    bcc = Ariadne.service.broadcast

    sched = app.create(GraiaScheduler)

    @sched.schedule(every_custom_seconds(30))
    async def print_ver(app: Ariadne):
        logger.debug(await app.getVersion())

    async def chk(msg: MessageChain):
        return msg.asDisplay().endswith("override")

    @bcc.receiver(CommandExecutedEvent)
    async def print_remote_cmd(event: CommandExecutedEvent):
        logger.debug(event)

    @bcc.receiver(
        MessageEvent,
        dispatchers=[CoolDown(5, override_condition=chk, stop_on_cooldown=True)],
        decorators=[DetectPrefix("trigger_wait")],
    )
    async def hdlr(
        ev: MessageEvent,
        res_time: Optional[float],
        app: Ariadne,
        sender: Union[Friend, Member],
    ):
        await app.sendMessage(
            ev,
            MessageChain(
                [f"""rest: {res_time}s, from {getattr(sender, "name", getattr(sender, "nickname", None))}"""]
            ),
        )

    @bcc.receiver(MessageEvent)
    async def send(app: Ariadne, ev: MessageEvent, chain: MessageChain = MentionMe()):
        logger.debug(repr(chain))
        if chain.asDisplay().startswith(".wait"):
            await app.sendMessage(ev, MessageChain.create("Wait for 5s!"))
            await asyncio.sleep(5.0)
            await app.sendMessage(ev, MessageChain.create("Complete!"))

    @bcc.receiver(MessageEvent)
    async def check_multi(chain: MessageChain):
        if chain.has(MultimediaElement):
            elem = chain.getFirst(MultimediaElement)
            logger.info(elem.dict())

    @bcc.receiver(GroupEvent)
    async def log(group: Group):
        logger.info(repr(group))

    @bcc.receiver(
        GroupMessage, decorators=[CertainGroup(int(t_group))], dispatchers=[FuzzyDispatcher("github")]
    )
    async def reply_to_me(app: Ariadne, ev: MessageEvent, rate: float):
        await app.sendMessage(ev, MessageChain.create(f"Git host! rate: {rate}"))

    @bcc.receiver(
        GroupMessage, decorators=[CertainGroup(int(t_group))], dispatchers=[FuzzyDispatcher("gayhub")]
    )
    async def reply_to_me(app: Ariadne, ev: MessageEvent, rate: float):
        await app.sendMessage(ev, MessageChain.create(f"Gay host! rate: {rate}"))

    @bcc.receiver(ExceptionThrowed)
    async def e(app: Ariadne, e: ExceptionThrowed):
        await app.sendMessage(e.event, MessageChain.create(f"{e.exception}"))

    @bcc.receiver(MessageEvent, decorators=[MatchContent("!raise")])
    async def raise_(app: Ariadne, ev: MessageEvent):
        await app.sendMessage(ev, MessageChain.create("Raise!"))
        raise ValueError("Raised!")

    @bcc.receiver(
        MessageEvent,
        dispatchers=[
            Twilight(
                [
                    FullMatch(".test"),
                    "help" @ ArgumentMatch("--help", "-h", action="store_true"),
                    "arg" @ WildcardMatch().flags(re.DOTALL),
                    "verbose" @ ArgumentMatch("--verbose", action="store_true"),
                ]
            )
        ],
    )
    async def reply1(
        app: Ariadne,
        event: MessageEvent,
        arg: RegexResult,
        help: ArgResult,
        twilight: Twilight,
        verbose: ArgResult,
    ):
        if help.matched:
            return await app.sendMessage(
                event, MessageChain.create(twilight.get_help(description="Foo help!"))
            )
        if verbose.matched:
            await app.sendMessage(event, MessageChain.create("Auto reply to \n") + arg.result)
        else:
            await app.sendMessage(event, MessageChain.create("Result: ") + arg.result)

    @bcc.receiver(NewFriendRequestEvent)
    async def accept(event: NewFriendRequestEvent):
        await event.accept("Welcome!")

    @bcc.receiver(MessageEvent, dispatchers=[Twilight([FullMatch(".test")])])
    async def reply2(app: Ariadne, event: MessageEvent):
        await app.sendMessage(event, MessageChain.create("Auto reply to /test!"))

    def unwind(fwd: Forward):
        for node in fwd.nodeList:
            if node.messageChain.has(Forward):
                unwind(node.messageChain.getFirst(Forward))
            else:
                logger.debug(node.messageChain.asDisplay())

    @bcc.receiver(MessageEvent)
    async def unwind_fwd(chain: MessageChain):
        if chain.has(Forward):
            unwind(chain.getFirst(Forward))

    @bcc.receiver(GroupMessage)
    async def reply3(app: Ariadne, chain: MessageChain, group: Group, member: Member):
        if "Hi!" in chain and chain.has(At):
            await app.sendGroupMessage(
                group,
                MessageChain.create([At(chain.getFirst(At).target), Plain("Hello World!")]),
            )  # WARNING: May raise UnknownTarget

    @bcc.receiver(GroupRecallEvent)
    async def anti_recall(app: Ariadne, event: GroupRecallEvent):
        msg = await app.getMessageFromId(event.messageId)
        await app.sendGroupMessage(event.group, msg.messageChain)

    @bcc.receiver(
        FriendMessage,
        dispatchers=[Twilight([RegexMatch("[./]stop")])],
    )
    async def stop(app: Ariadne):
        app.stop()

    @bcc.receiver(ApplicationLaunched)
    async def m(app: Ariadne):
        await app.sendFriendMessage(target, MessageChain.create("Launched!"))

    @bcc.receiver(ApplicationShutdowned)
    async def m(app: Ariadne):
        await app.sendFriendMessage(target, MessageChain.create("Shutdown!"))

    @bcc.receiver(CommandExecutedEvent)
    async def cmd_log(event: CommandExecutedEvent):
        devtools.debug(event)

    async def main():
        await app.launch()
        await app.connection.status.wait_for_available()
        logger.debug(await app.getVersion())
        logger.debug(await app.getBotProfile())
        if ALL_FLAG:
            group_list = await app.getGroupList()
            await app.registerCommand("graia_cmd", ["graiax", "gx"], "graia_cmd <a> <b> <c>", "Test graia")
            logger.debug(group_list)
            friend_list = await app.getFriendList()
            logger.debug(friend_list)
            member_list = await app.getMemberList(group_list[0])
            logger.debug(member_list)
            logger.debug(await app.getFriendProfile(friend_list[0]))
            logger.debug(await app.getMemberProfile(member_list[0], group_list[0]))
            logger.debug(await app.getMemberProfile(member_list[0]))
        await app.lifecycle()

    Ariadne.launch_blocking()
