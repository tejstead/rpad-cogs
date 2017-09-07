import asyncio
import inspect
from pathlib import Path
import re
import unicodedata

import discord
from discord.ext import commands
from discord.ext.commands import CommandNotFound
from discord.ext.commands import converter

from cogs.utils.chat_formatting import *

from .utils.dataIO import fileIO
from .utils.padguide_api import *


class RpadUtils:
    def __init__(self, bot):
        self.bot = bot

    async def on_command_error(self, error, ctx):
        channel = ctx.message.channel
        if isinstance(error, ReportableError):
            await self.bot.send_message(channel, error.message)


def setup(bot):
    print('rpadutils setup')
    n = RpadUtils(bot)
    bot.add_cog(n)


# TZ used for PAD NA
# NA_TZ_OBJ = pytz.timezone('America/Los_Angeles')
NA_TZ_OBJ = pytz.timezone('US/Pacific')

# TZ used for PAD JP
JP_TZ_OBJ = pytz.timezone('Asia/Tokyo')


# https://gist.github.com/ryanmcgrath/982242
# UNICODE RANGE : DESCRIPTION
# 3000-303F : punctuation
# 3040-309F : hiragana
# 30A0-30FF : katakana
# FF00-FFEF : Full-width roman + half-width katakana
# 4E00-9FAF : Common and uncommon kanji
#
# Non-Japanese punctuation/formatting characters commonly used in Japanese text
# 2605-2606 : Stars
# 2190-2195 : Arrows
# u203B     : Weird asterisk thing

JP_REGEX_STR = r'[\u3000-\u303F]|[\u3040-\u309F]|[\u30A0-\u30FF]|[\uFF00-\uFFEF]|[\u4E00-\u9FAF]|[\u2605-\u2606]|[\u2190-\u2195]|\u203B'
JP_REGEX = re.compile(JP_REGEX_STR)


def containsJp(txt):
    return JP_REGEX.search(txt)


class ReportableError(commands.CheckFailure):
    """Throw when an exception should be reported to the user."""

    def __init__(self, message):
        self.message = message
        super(ReportableError, self).__init__(message)


class PermissionsError(CommandNotFound):
    """
    Base exception for all others in this module
    """


class BadCommand(PermissionsError):
    """
    Thrown when we can't decipher a command from string into a command object.
    """
    pass


class RoleNotFound(PermissionsError):
    """
    Thrown when we can't get a valid role from a list and given name
    """
    pass


class SpaceNotation(BadCommand):
    """
    Throw when, with some certainty, we can say that a command was space
        notated, which would only occur when some idiot...fishy...tries to
        surround a command in quotes.
    """
    pass


def get_role(roles, role_string):
    if role_string.lower() == "everyone":
        role_string = "@everyone"

    role = discord.utils.find(
        lambda r: r.name.lower() == role_string.lower(), roles)

    if role is None:
        raise RoleNotFound()

    return role


def get_role_from_id(bot, server, roleid):
    try:
        roles = server.roles
    except AttributeError:
        server = get_server_from_id(bot, server)
        try:
            roles = server.roles
        except AttributeError:
            raise RoleNotFound(server, roleid)

    role = discord.utils.get(roles, id=roleid)
    if role is None:
        raise RoleNotFound(server, roleid)
    return role


def get_server_from_id(bot, serverid):
    return discord.utils.get(bot.servers, id=serverid)


def normalizeServer(server):
    server = server.upper()
    return 'NA' if server == 'US' else server


cache_folder = 'data/padevents'


def should_download(file_path, expiry_secs):
    if not os.path.exists(file_path):
        print("file does not exist, downloading " + file_path)
        return True

    ftime = os.path.getmtime(file_path)
    file_age = time.time() - ftime
    print("for " + file_path + " got " + str(ftime) + ", age " +
          str(file_age) + " against expiry of " + str(expiry_secs))

    if file_age > expiry_secs:
        print("file too old, download it")
        return True
    else:
        return False


def shouldDownload(file_path, expiry_secs):
    return should_download(file_path, expiry_secs)


def writeJsonFile(file_path, js_data):
    with open(file_path, "w") as f:
        json.dump(js_data, f, sort_keys=True, indent=4)


def readJsonFile(file_path):
    with open(file_path, "r") as f:
        return json.load(f)


def checkPadguideCacheFile(cache_file, expiry_secs):
    """Cache_file and expiry secs are used to determine if we should make the request."""
    if shouldDownload(cache_file, expiry_secs):
        Path(cache_file).touch()
        return True
    return False


async def async_cached_padguide_request(endpoint, result_file):
    """Make a request to the PadGuide API.

    The endpoint is the JSP file name on the PadGuide API.
    The result_file is the place to store the resulting file."""
    time_ms = 0  # Pull for all-time
    resp = await async_padguide_ts_request(time_ms, endpoint)
    writeJsonFile(result_file, resp)


def writePlainFile(file_path, text_data):
    with open(file_path, "wt", encoding='utf-8') as f:
        f.write(text_data)


def readPlainFile(file_path):
    with open(file_path, "r", encoding='utf-8') as f:
        return f.read()


def makePlainRequest(file_url):
    response = urllib.request.urlopen(file_url)
    data = response.read()  # a `bytes` object
    return data.decode('utf-8')


def makeCachedPlainRequest2(file_path, file_url, expiry_secs):
    if shouldDownload(file_path, expiry_secs):
        resp = makePlainRequest(file_url)
        writePlainFile(file_path, resp)
    return readPlainFile(file_path)


async def boxPagifySay(say_fn, msg):
    for page in pagify(msg, delims=["\n"]):
        await say_fn(box(page))


class Forbidden():
    pass


def default_check(reaction, user):
    if user.bot:
        return False
    else:
        return True


class Menu():
    def __init__(self, bot):
        self.bot = bot

        # Feel free to override this in your cog if you need to
        self.emoji = {
            0: "0⃣",
            1: "1⃣",
            2: "2⃣",
            3: "3⃣",
            4: "4⃣",
            5: "5⃣",
            6: "6⃣",
            7: "7⃣",
            8: "8⃣",
            9: "9⃣",
            10: "🔟",
            "next": "➡",
            "back": "⬅",
            "yes": "✅",
            "no": "❌",
        }

    # for use as an action
    async def reaction_delete_message(self, bot, ctx, message):
        await bot.delete_message(message)

#     def perms(self, ctx):
#         user = ctx.message.server.get_member(self.bot.user.id)
#         return ctx.message.channel.permissions_for(user)

    async def custom_menu(self, ctx, emoji_to_message, selected_emoji, **kwargs):
        """Creates and manages a new menu
        Required arguments:
            Type:
                1- number menu
                2- confirmation menu
                3- info menu (basically menu pagination)
                4- custom menu. If selected, choices must be a list of tuples.
            Messages:
                Strings or embeds to use for the menu.
                Pass as a list for number menu
        Optional agruments:
            page (Defaults to 0):
                The message in messages that will be displayed
            timeout (Defaults to 15):
                The number of seconds until the menu automatically expires
            check (Defaults to default_check):
                The same check that wait_for_reaction takes
            is_open (Defaults to False):
                Whether or not the menu can take input from any user
            emoji (Decaults to self.emoji):
                A dictionary containing emoji to use for the menu.
                If you pass this, use the same naming scheme as self.emoji
            message (Defaults to None):
                The discord.Message to edit if present
            """
        return await self._custom_menu(ctx, emoji_to_message, selected_emoji, **kwargs)

    async def show_menu(self,
                        ctx,
                        message,
                        new_message_content):
        if message:
            if type(new_message_content) == discord.Embed:
                return await self.bot.edit_message(message, embed=new_message_content)
            else:
                return await self.bot.edit_message(message, new_message_content)
        else:
            if type(new_message_content) == discord.Embed:
                return await self.bot.send_message(ctx.message.channel,
                                                   embed=new_message_content)
            else:
                return await self.bot.say(new_message_content)

    async def _custom_menu(self, ctx, emoji_to_message, selected_emoji, **kwargs):
        timeout = kwargs.get('timeout', 15)
        check = kwargs.get('check', default_check)
        message = kwargs.get('message', None)

        reactions_required = not message
        new_message_content = emoji_to_message[selected_emoji]
        message = await self.show_menu(ctx, message, new_message_content)

        if reactions_required:
            for e in emoji_to_message:
                try:
                    await self.bot.add_reaction(message, e)
                except Exception as e:
                    # failed to add reaction, ignore
                    pass

        r = await self.bot.wait_for_reaction(
            emoji=list(emoji_to_message.keys()),
            message=message,
            user=ctx.message.author,
            check=check,
            timeout=timeout)

        if r is None:
            try:
                await self.bot.clear_reactions(message)
            except Exception as e:
                # This is expected when miru doesn't have manage messages
                pass
            return message, new_message_content

        react_emoji = r.reaction.emoji
        react_action = emoji_to_message[r.reaction.emoji]

        if inspect.iscoroutinefunction(react_action):
            message = await react_action(self.bot, ctx, message)
        elif inspect.isfunction(react_action):
            message = react_action(ctx, message)

        # user function killed message, quit
        if not message:
            return None, None

        try:
            await self.bot.remove_reaction(message, react_emoji, r.user)
        except:
            # This is expected when miru doesn't have manage messages
            pass

        return await self._custom_menu(
            ctx, emoji_to_message, react_emoji,
            timeout=timeout,
            check=check,
            message=message)


def char_to_emoji(c):
    c = c.lower()
    if c < 'a' or c > 'z':
        return c

    base = ord('\N{REGIONAL INDICATOR SYMBOL LETTER A}')
    adjustment = ord(c) - ord('a')
    return chr(base + adjustment)


##############################
# Hack to fix discord.py
##############################
class UserConverter2(converter.IDConverter):
    @asyncio.coroutine
    def convert(self):
        message = self.ctx.message
        bot = self.ctx.bot
        match = self._get_id_match() or re.match(r'<@!?([0-9]+)>$', self.argument)
        server = message.server
        result = None
        if match is None:
            # not a mention...
            if server:
                result = server.get_member_named(self.argument)
            else:
                result = _get_from_servers(bot, 'get_member_named', self.argument)
        else:
            user_id = match.group(1)
            if server:
                result = yield from bot.get_user_info(user_id)
            else:
                result = _get_from_servers(bot, 'get_member', user_id)

        if result is None:
            raise BadArgument('Member "{}" not found'.format(self.argument))

        return result


converter.UserConverter = UserConverter2

##############################
# End hack to fix discord.py
##############################


def fix_emojis_for_server(emoji_list, msg_text):
    """Finds 'emoji-looking' substrings in msg_text and corrects them.

    If msg_text has something like '<:emoji_1_derp:13242342343>' and the server
    contains an emoji named :emoji_2_derp: then it will be swapped out in
    the message.

    This corrects an issue where a padglobal alias is created in one server
    with an emoji, but it has a slightly different name in another server.
    """
    # Find all emoji-looking things in the message
    matches = re.findall(r'<:[0-9a-z_]+:\d{18}>', msg_text, re.IGNORECASE)
    if not matches:
        return msg_text

    # For each unique looking emoji thing
    for m in set(matches):
        # Create a regex for that emoji replacing the digit
        m_re = re.sub(r'\d', r'\d', m)
        for em in emoji_list:
            # If the current emoji matches the regex, force a replacement
            emoji_code = str(em)
            if re.match(m_re, emoji_code, re.IGNORECASE):
                msg_text = re.sub(m_re, emoji_code, msg_text, flags=re.IGNORECASE)
                break
    return msg_text


def is_valid_image_url(url):
    url = url.lower()
    return url.startswith('http') and (url.endswith('.png') or url.endswith('.jpg'))


def extract_image_url(m):
    if is_valid_image_url(m.content):
        return m.content
    if m.attachments and len(m.attachments) and is_valid_image_url(m.attachments[0]['url']):
        return m.attachments[0]['url']
    return None


def rmdiacritics(input):
    '''
    Return the base character of char, by "removing" any
    diacritics like accents or curls and strokes and the like.
    '''
    output = ''
    for c in input:
        try:
            desc = unicodedata.name(c)
            cutoff = desc.find(' WITH ')
            if cutoff != -1:
                desc = desc[:cutoff]
            output += unicodedata.lookup(desc)
        except:
            output += c
    return output


def clean_global_mentions(content):
    """Wipes out mentions to @everyone and @here."""
    return re.sub(r'(@)(\w)', '\\g<1>\u200b\\g<2>', content)


class CogSettings:
    BASE_DATA_PATH = "data"
    SETTINGS_FILE_NAME = "settings.json"

    def __init__(self, cog_name):
        self.folder = CogSettings.BASE_DATA_PATH + "/" + cog_name
        self.file_path = self.folder + "/" + CogSettings.SETTINGS_FILE_NAME

        self.check_folder()

        self.default_settings = self.make_default_settings()
        if not fileIO(self.file_path, "check"):
            self.bot_settings = self.default_settings
            self.save_settings()
        else:
            current = fileIO(self.file_path, "load")
            updated = False
            for key in self.default_settings.keys():
                if key not in current.keys():
                    current[key] = self.default_settings[key]
                    updated = True

            self.bot_settings = current
            if updated:
                self.save_settings()

    def check_folder(self):
        if not os.path.exists(self.folder):
            print("Creating " + self.folder)
            os.makedirs(self.folder)

    def save_settings(self):
        fileIO(self.file_path, "save", self.bot_settings)

    def make_default_settings(self):
        return {}

    # TODO: maybe centralize get_server / get_server_channel stuff since i do that everywhere
    def getServerSettings(self, server_id):
        if 'cmd_whitelist_blacklist' not in self.bot_settings:
            self.bot_settings['cmd_whitelist_blacklist'] = {}

        settings = self.bot_settings['cmd_whitelist_blacklist']
        if server_id not in settings:
            settings[server_id] = {}

        return settings[server_id]
