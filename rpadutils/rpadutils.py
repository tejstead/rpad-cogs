import re

import discord
from discord.ext import commands


class RpadUtils:
    def __init__(self, bot):
        self.bot = bot

def setup(bot):
    print('rpadutils setup')
    n = RpadUtils(bot)
    bot.add_cog(n)

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

JP_REGEX_STR = r'[\u3000-\u303F]|[\u3040-\u309F]|[\u30A0-\u30FF]|[\uFF00-\uFFEF]|[\u4E00-\u9FAF]|[\u2605-\u2606]|[\u2190-\u2195]|\u203B';
JP_REGEX = re.compile(JP_REGEX_STR)

def containsJp(txt):
    return JP_REGEX.search(txt)


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
        raise RoleNotFound(roles[0].server, role_string)

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
