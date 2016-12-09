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

