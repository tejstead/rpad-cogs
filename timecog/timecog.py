import discord
from discord.ext import commands
from .utils.chat_formatting import *
from .utils.dataIO import fileIO
from .utils import checks
from __main__ import send_cmd_help
import os

import time
from datetime import datetime
from datetime import timedelta
from dateutil import tz
import pytz

tz_lookup = dict([(pytz.timezone(x).localize(datetime.now()).tzname(), pytz.timezone(x)) for x in pytz.all_timezones])

class TimeCog:
    """Utilities to convert time"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="time", pass_context=True)
    async def time(self, ctx, tz):
        """Converts time"""
        try:
            tz_obj = tzStrToObj(tz)
        except Exception as e:
            await self.bot.say("Failed to parse tz: " + tz)
            return

        now = datetime.now(tz_obj)
        msg = "The time in " + now.strftime('%Z') + " is " + fmtTimeShort(now).strip()
        await self.bot.say(inline(msg))

    @commands.command(name="timeto", pass_context=True)
    async def timeto(self, ctx, tz, time):
        """Converts time"""
        try:
            tz_obj = tzStrToObj(tz)
        except Exception as e:
            await self.bot.say("Failed to parse tz: " + tz)
            return

        try:
            time_obj = timeStrToObj(time)
        except Exception as e:
            print(e)
            await self.bot.say("Failed to parse time: " + time)
            return

        now = datetime.now(tz_obj)
        req_time = now.replace(hour=time_obj.tm_hour, minute=time_obj.tm_min)

        if req_time < now:
            req_time = req_time + timedelta(days=1)
        delta = req_time - now

        msg = "There are " + fmtHrsMins(delta.seconds).strip() + " until " + time.strip() + " in " + now.strftime('%Z')
        await self.bot.say(inline(msg))

#     @commands.command(name="timefrom", pass_context=True)
#     async def timefrom(self, ctx, from_tz, from_time, to_tz, to_time):
#         """Converts time"""
#         try:
#             from_tz_obj = tzStrToObj(from_tz)
#         except Exception as e:
#             await self.bot.say("Failed to parse from tz: " + from_tz)
#             return
#         try:
#             to_tz_obj = tzStrToObj(to_tz)
#         except Exception as e:
#             await self.bot.say("Failed to parse to tz: " + to_tz)
#             return
#
#         try:
#             from_time_obj = timeStrToObj(from_time)
#         except Exception as e:
#             await self.bot.say("Failed to parse from time: " + from_time)
#             return
#
#         try:
#             to_time_obj = timeStrToObj(to_time)
#         except Exception as e:
#             await self.bot.say("Failed to parse from time: " + to_time)
#             return
#
#         now = datetime.now(tz_obj)
#         req_time = now.replace(hour=time_obj.tm_hour, minute=time_obj.tm_min)
#
#         if req_time < now:
#             req_time = req_time + timedelta(days=1)
#         delta = req_time - now
#
#         msg = "There are " + fmtHrsMins(delta.seconds).strip() + " until " + time.strip() + " in " + now.strftime('%Z')
#         await self.bot.say(inline(msg))

def timeStrToObj(timestr):
    timestr = timestr.replace(" ", "")
    try:
        return time.strptime(timestr, "%H:%M")
    except:
        pass
    try:
        return time.strptime(timestr, "%I:%M%p")
    except:
        pass
    try:
        return time.strptime(timestr, "%I%p")
    except:
        pass
    raise Exception()

def fmtHrsMins(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return '{:2}hrs {:2}mins'.format(int(hours), int(minutes))

def fmtTimeShort(dt):
    return dt.strftime("%I:%M %p")

def tzStrToObj(tz):
    tz = tz.lower().strip()
    if tz in ['edt', 'est', 'et']:
        tz = 'America/New_York'
    elif tz in ['mdt', 'mst', 'mt']:
        tz = 'America/North_Dakota'
    elif tz in ['pdt', 'pst', 'pt']:
        tz = 'America/Los_Angeles'
    elif tz in ['jp', 'jt', 'jst']:
        return tz_lookup['JST']
    else:
        return tz_lookup[tz.upper()]

    tz_obj = pytz.timezone(tz)
    return tz_obj

def setup(bot):
    n = TimeCog(bot)
    bot.add_cog(n)
