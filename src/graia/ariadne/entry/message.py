"""Ariadne 消息相关的导入集合"""

# no error

from ..message.chain import MessageChain
from ..message.component import Component
from ..message.element import (
    App,
    At,
    AtAll,
    Dice,
    Element,
    Face,
    File,
    FlashImage,
    Forward,
    ForwardNode,
    Image,
    ImageType,
    MultimediaElement,
    MusicShare,
    NotSendableElement,
    Plain,
    Poke,
    PokeMethods,
    Quote,
    Source,
    Voice,
)
from ..message.formatter import Formatter
from ..message.parser.alconna import (
    Alconna,
    AlconnaDispatcher,
    AnyDigit,
    AnyIP,
    AnyStr,
    AnyUrl,
    Arpamar,
    ArpamarProperty,
    Bool,
    CommandInterface,
    Default,
    InvalidFormatMap,
    InvalidOptionName,
    NullName,
    Option,
    OptionInterface,
    ParamsUnmatched,
    Subcommand,
)
from ..message.parser.base import DetectPrefix, DetectSuffix
from ..message.parser.literature import (
    BoxParameter,
    Literature,
    ParamPattern,
    SwitchParameter,
)
from ..message.parser.twilight import (
    FORCE,
    NOSPACE,
    PRESERVE,
    ArgumentMatch,
    ElementMatch,
    FullMatch,
    Match,
    RegexMatch,
    Sparkle,
    Twilight,
    UnionMatch,
    WildcardMatch,
)
