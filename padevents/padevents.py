import asyncio
from collections import defaultdict
from datetime import datetime
from datetime import timedelta
from enum import Enum
import http.client
import json
import os
import re
import threading
import time
import time
import traceback
import urllib.parse

from dateutil import tz
import discord
from discord.ext import commands
import prettytable
import pytz

from __main__ import user_allowed, send_cmd_help

from . import padguide
from .rpadutils import *
from .utils import checks
from .utils.chat_formatting import *
from .utils.cog_settings import *
from .utils.dataIO import fileIO
from .utils.twitter_stream import *


SUPPORTED_SERVERS = ["NA", "KR", "JP", "FAKE"]

def dl_events():
    # two hours expiry
    expiry_secs = 2 * 60 * 60
    # pull last two weeks of events
    time_ms = int(round(time.time() * 1000)) - 14 * 24 * 60 * 60 * 1000
    resp = makeCachedPadguideRequest(time_ms, "scheduleList.jsp", expiry_secs)
    events = list()
    for item in resp["items"]:
        events.append(padguide.PgEvent(item))
    return events

def dl_event_type_map():
    # eight hours expiry
    expiry_secs = 8 * 60 * 60
    # pull for all-time
    time_ms = 0
    resp = makeCachedPadguideRequest(time_ms, "eventList.jsp", expiry_secs)
    etype_map = dict()
    for item in resp["items"]:
        etype = padguide.PgEventType(item)
        etype_map[etype.seq] = etype
    return etype_map


def dl_dungeon_map():
    # eight hours expiry
    expiry_secs = 8 * 60 * 60
    # pull for all-time
    time_ms = 0
    resp = makeCachedPadguideRequest(time_ms, "dungeonList.jsp", expiry_secs)
    dungeons_map = dict()
    for item in resp["items"]:
        dungeon = padguide.PgDungeon(item)
        dungeons_map[dungeon.seq] = dungeon
    return dungeons_map

EXTRA_FILES = [
    "attributeList.jsp",
    "awokenSkillList.jsp",
#     "dungeonList.jsp",
    "dungeonTypeList.jsp",
    "dungeonMonsterList.jsp",
    "dungeonMonsterDropList.jsp",
    "dungeonTypeList.jsp",
    "eggCategoryList.jsp",
    "eggCategoryNameList.jsp",
    "eggMonsterList.jsp",
    "eggTitleList.jsp",
    "eggTitleNameList.jsp",
    "evolutionList.jsp",
    "monsterAddInfoList.jsp",
    "monsterInfoList.jsp",
    "monsterList.jsp",
    "skillDataList.jsp",
    "skillLeaderDataList.jsp",
    "seriesList.jsp",
    "skillList.jsp",
    "skillRotationList.jsp",
    "skillRotationListList.jsp",
    "typeList.jsp",
]

def clear_extras():
    for ef in EXTRA_FILES:
        rmCachedPadguideRequest(ef)

def dl_extras():
    # three days expiry
    expiry_secs = 3 * 24 * 60 * 60
    # pull for all-time
    time_ms = 0
    for ef in EXTRA_FILES:
        makeCachedPadguideRequest(time_ms, ef, expiry_secs)


class PadEvents:
    def __init__(self, bot):
        self.bot = bot

        self.settings = PadEventSettings("padevents")

        # Load all dungeon data
        self.dungeons_map = dl_dungeon_map()
        self.event_type_map = dl_event_type_map()

        # DL extra files and cache locally
        dl_extras()

        # Load event data
        self.events = list()
        self.started_events = set()

        self.fake_uid = -999

    def __unload(self):
        print("unloading padevents")
        self.reload_events_task.cancel()
        self.check_started_task.cancel()

    def registerTasks(self, event_loop):
        print("registering tasks")
        self.reload_events_task = event_loop.create_task(self.reload_events())
        self.check_started_task = event_loop.create_task(self.check_started())

    def loadEvents(self):
        self.events = dl_events()
        self.started_events = set()

        for e in self.events:
            e.updateDungeonName(self.dungeons_map)
            e.updateEventModifier(self.event_type_map)
            if e.isStarted():
                self.started_events.add(e.uid)

        print(str(len(self.started_events)) + " events already started")
        print(str(len(self.events) - len(self.started_events)) + " events pending")

    async def on_ready(self):
        """ready"""
        print("started padevents")

    @commands.group(pass_context=True, no_pm=True)
    async def padevents(self, ctx):
        """PAD event tracking"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    async def check_started(self):
        print("starting check_started")
        while "PadEvents" in self.bot.cogs:
            try:
                events = filter(lambda e: e.isStarted() and not e.uid in self.started_events, self.events)

                daily_refresh_servers = set()
                for e in events:
                    self.started_events.add(e.uid)
                    if e.event_type in [padguide.EventType.EventTypeGuerrilla, padguide.EventType.EventTypeGuerrillaNew]:
                        for gr in list(self.settings.listGuerrillaReg()):
                            if e.server == gr['server']:
                                try:
                                    message = box("Server " + e.server + ", group " + e.group + " : " + e.nameAndModifier())
                                    channel = self.bot.get_channel(gr['channel_id'])

                                    try:
                                        role_name = '{}_group_{}'.format(e.server, e.group)
                                        role = get_role(channel.server.roles, role_name)
                                        if role and role.mentionable:
                                            message = "{} `: {} is starting`".format(role.mention, e.nameAndModifier())
                                    except:
                                        pass  # do nothing if role is missing

                                    await self.bot.send_message(channel, message)
                                except Exception as ex:
                                    # deregister gr
                                    traceback.print_exc()
                                    print("caught exception while sending guerrilla msg, deregistering " + str(ex))
                                    print('for ' + channel.name + ' sending ' + message)
                                    self.settings.removeGuerrillaReg(gr['channel_id'], gr['server'])

                    else:
                        if not e.isForNormal():
                            daily_refresh_servers.add(e.server)

                for server in daily_refresh_servers:
                    msg = self.makeActiveText(server)
                    for daily_registration in list(self.settings.listDailyReg()):
                        try:
                            if server == daily_registration['server']:
                                await self.pageOutput(msg, channel_id=daily_registration['channel_id'])
                        except Exception as ex:
                            traceback.print_exc()
                            print("caught exception while sending daily msg, deregistering " + str(ex))
                            self.settings.removeDailyReg(daily_registration['channel_id'], daily_registration['server'])


            except Exception as ex:
                traceback.print_exc()
                print("caught exception while checking guerrillas " + str(ex))

            try:
                await asyncio.sleep(10)
            except Exception as ex:
                traceback.print_exc()
                print("check event loop caught exception " + str(ex))
                raise ex
        print("done check_started")

    async def reload_events(self):
        print("event reloader")
        while "PadEvents" in self.bot.cogs:
            do_short = False
            try:
                self.loadEvents()
            except Exception as e:
                traceback.print_exc()
                do_short = True
                print("caught exception while loading events " + str(e))

            try:
                if do_short:
                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(60 * 60 * 4)
            except Exception as e:
                print("reload event loop caught exception " + str(e))
                raise e

        print("done reload_events")

    @padevents.command(name="testevent", pass_context=True, no_pm=True)
    @checks.is_owner()
    async def _testevent(self, ctx, server):
        print(SUPPORTED_SERVERS)
        print(server)
        server = normalizeServer(server)
        print(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say("Unsupported server, pick one of NA, KR, JP")
            return

        te = padguide.PgEvent(None, ignore_bad=True)
        te.server = server

        te.dungeon_code = 1
        te.event_type = padguide.EventType.EventTypeGuerrilla
        te.event_seq = 0
        self.fake_uid = self.fake_uid - 1
        te.uid = self.fake_uid
        te.group = 'F'

        te.open_datetime = datetime.now(pytz.utc)
        te.close_datetime = te.open_datetime + timedelta(minutes=1)
        te.dungeon_name = 'fake_dungeon_name'
        te.event_modifier = 'fake_event_modifier'
        self.events.append(te)

        await self.bot.say("Fake event injected.")

    @padevents.command(pass_context=True)
    @checks.is_owner()
    async def clearcache(self, ctx):
        clear_extras()
        await self.bot.say("Cached files cleared. Downloads started.")
        dl_extras()
        await self.bot.say("Done.")

    @padevents.command(name="addchannel", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def _addchannel(self, ctx, server):
        server = normalizeServer(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say("Unsupported server, pick one of NA, KR, JP")
            return

        channel_id = ctx.message.channel.id
        if self.settings.checkGuerrillaReg(channel_id, server):
            await self.bot.say("Channel already active.")
            return

        self.settings.addGuerrillaReg(channel_id, server)
        await self.bot.say("Channel now active.")

    @padevents.command(name="rmchannel", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def _rmchannel(self, ctx, server):
        server = normalizeServer(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say("Unsupported server, pick one of NA, KR, JP")
            return

        channel_id = ctx.message.channel.id
        if not self.settings.checkGuerrillaReg(channel_id, server):
            await self.bot.say("Channel is not active.")
            return

        self.settings.removeGuerrillaReg(channel_id, server)
        await self.bot.say("Channel deactivated.")

    @padevents.command(name="addchanneldaily", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def _addchanneldaily(self, ctx, server):
        server = normalizeServer(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say("Unsupported server, pick one of NA, KR, JP")
            return

        channel_id = ctx.message.channel.id
        if self.settings.checkDailyReg(channel_id, server):
            await self.bot.say("Channel already active.")
            return

        self.settings.addDailyReg(channel_id, server)
        await self.bot.say("Channel now active.")

    @padevents.command(name="rmchanneldaily", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def _rmchanneldaily(self, ctx, server):
        server = normalizeServer(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say("Unsupported server, pick one of NA, KR, JP")
            return

        channel_id = ctx.message.channel.id
        if not self.settings.checkDailyReg(channel_id, server):
            await self.bot.say("Channel is not active.")
            return

        self.settings.removeDailyReg(channel_id, server)
        await self.bot.say("Channel deactivated.")

    @padevents.command(name="listchannels", pass_context=True)
    @checks.mod_or_permissions(manage_server=True)
    async def _listchannel(self, ctx):
        msg = 'Following daily channels are registered:\n'
        msg += self.makeChannelList(self.settings.listDailyReg())
        msg += "\n"
        msg += 'Following guerilla channels are registered:\n'
        msg += self.makeChannelList(self.settings.listGuerrillaReg())
        await self.pageOutput(msg)

    def makeChannelList(self, reg_list):
        msg = ""
        for cr in reg_list:
            reg_channel_id = cr['channel_id']
            channel = self.bot.get_channel(reg_channel_id)
            channel_name = channel.name if channel else 'Unknown(' + reg_channel_id + ')'
            server_name = channel.server.name if channel else 'Unknown server'
            msg += "   " + cr['server'] + " : " + server_name + '(' + channel_name + ')\n'
        return msg

    @padevents.command(name="active", pass_context=True)
    @checks.mod_or_permissions(manage_server=True)
    async def _active(self, ctx, server):
        server = normalizeServer(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say("Unsupported server, pick one of NA, KR, JP")
            return

        msg = self.makeActiveText(server)
#         await self.pageOutput(msg, format_type=inline)
        await self.pageOutput(msg)

    def makeActiveText(self, server):
        server_events = padguide.PgEventList(self.events).withServer(server)
        active_events = server_events.activeOnly()
        pending_events = server_events.pendingOnly()
        available_events = server_events.availableOnly()

        msg = "Listing all events for " + server

        special_events = active_events.withType(padguide.EventType.EventTypeSpecial).itemsByCloseTime()
        if len(special_events) > 0:
            msg += "\n\n" + self.makeActiveOutput('Special Events', special_events)

        all_etc_events = active_events.withType(padguide.EventType.EventTypeEtc)

        etc_events = all_etc_events.withDungeonType(padguide.DungeonType.Etc).excludeUnwantedEvents().itemsByCloseTime()
        if len(etc_events) > 0:
            msg += "\n\n" + self.makeActiveOutput('Etc Events', etc_events)

#         tech_events = all_etc_events.withDungeonType(DungeonType.Technical).withNameContains('legendary').itemsByCloseTime()
#         if len(etc_events) > 0:
#             msg += "\n\n" + self.makeActiveOutput('Technical Events', tech_events)

        active_guerrilla_events = active_events.withType(padguide.EventType.EventTypeGuerrilla).items()
        if len(active_guerrilla_events) > 0:
            msg += "\n\n" + self.makeActiveGuerrillaOutput('Active Guerrillas', active_guerrilla_events)

        guerrilla_events = pending_events.withType(padguide.EventType.EventTypeGuerrilla).items()
        if len(guerrilla_events) > 0:
            msg += "\n\n" + self.makeFullGuerrillaOutput('Guerrilla Events', guerrilla_events)

        week_events = available_events.withType(padguide.EventType.EventTypeWeek).items()
        if len(week_events):
            msg += "\n\n" + "Found " + str(len(week_events)) + " unexpected week events!"

        special_week_events = available_events.withType(padguide.EventType.EventTypeSpecialWeek).items()
        if len(special_week_events):
            msg += "\n\n" + "Found " + str(len(special_week_events)) + " unexpected special week events!"

        active_guerrilla_new_events = active_events.withType(padguide.EventType.EventTypeGuerrillaNew).items()
        if len(active_guerrilla_new_events) > 0:
            msg += "\n\n" + self.makeActiveGuerrillaOutput('Active New Guerrillas', active_guerrilla_new_events)

        guerrilla_new_events = pending_events.withType(padguide.EventType.EventTypeGuerrillaNew).items()
        if len(guerrilla_new_events) > 0:
            msg += "\n\n" + self.makeFullGuerrillaOutput('New Guerrilla Events', guerrilla_new_events, new_guerrilla=True)

        # clean up long headers
        msg = msg.replace('-------------------------------------', '-----------------------')

        return msg

    async def pageOutput(self, msg, channel_id=None, format_type=box):
        msg = msg.strip()
        msg = pagify(msg, ["\n"], shorten_by=20)
        for page in msg:
            try:
                if channel_id is None:
                    await self.bot.say(format_type(page))
                else:
                    await self.bot.send_message(discord.Object(channel_id), format_type(page))
            except Exception as e:
                print("page output failed " + str(e))
                print("tried to print: " + page)

    def makeActiveOutput(self, table_name, event_list):
        tbl = prettytable.PrettyTable(["Time", table_name])
        tbl.hrules = prettytable.HEADER
        tbl.vrules = prettytable.NONE
        tbl.align[table_name] = "l"
        tbl.align["Time"] = "r"
        for e in event_list:
            tbl.add_row([e.endFromNowFullMin().strip(), e.nameAndModifier()])
        return tbl.get_string()

    def makeActiveGuerrillaOutput(self, table_name, event_list):
        tbl = prettytable.PrettyTable([table_name, "Group", "Time"])
        tbl.hrules = prettytable.HEADER
        tbl.vrules = prettytable.NONE
        tbl.align[table_name] = "l"
        tbl.align["Time"] = "r"
        for e in event_list:
            tbl.add_row([e.nameAndModifier(), e.group, e.endFromNowFullMin().strip()])
        return tbl.get_string()

    def makeFullGuerrillaOutput(self, table_name, event_list, new_guerrilla=False):
        events_by_name = defaultdict(list)
        for e in event_list:
            events_by_name[e.name()].append(e)

        rows = list()
        grps = ["A", "B", "C"] if new_guerrilla else ["A", "B", "C", "D", "E"]
        for name, events in events_by_name.items():
            events = sorted(events, key=lambda e: e.open_datetime)
            events_by_group = defaultdict(list)
            for e in events:
                events_by_group[e.group].append(e)

            done = False
            while not done:
                did_work = False
                row = list()
                row.append(name)
                for g in grps:
                    grp_list = events_by_group[g]
                    if len(grp_list) == 0:
                        row.append("")
                    else:
                        did_work = True
                        e = grp_list.pop(0)
                        row.append(e.toGuerrillaStr())
                if did_work:
                    rows.append(row)
                else:
                    done = True

        col1 = "Pending"
        tbl = prettytable.PrettyTable([col1] + grps)
        tbl.align[col1] = "l"
        tbl.hrules = prettytable.HEADER
        tbl.vrules = prettytable.ALL

        for r in rows:
            tbl.add_row(r)

        header = "Times are PT below\n\n"
        return header + tbl.get_string() + "\n"

    @padevents.command(name="partial", pass_context=True)
    async def _partial(self, ctx, server):
        await self.doPartial(ctx, server)

    @commands.command(pass_context=True, aliases=['events'])
    async def eventsna(self, ctx):
        await self.doPartial(ctx, 'NA')

    @commands.command(pass_context=True)
    async def eventsjp(self, ctx):
        await self.doPartial(ctx, 'JP')

    async def doPartial(self, ctx, server):
        server = normalizeServer(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say("Unsupported server, pick one of NA, KR, JP")
            return

        events = padguide.PgEventList(self.events)
        events = events.withServer(server)
        events = events.withType(padguide.EventType.EventTypeGuerrilla)

        active_events = events.activeOnly().itemsByOpenTime(reverse=True)
        pending_events = events.pendingOnly().itemsByOpenTime(reverse=True)

        group_to_active_event = {e.group : e for e in active_events}
        group_to_pending_event = {e.group : e for e in pending_events}

        active_events = list(group_to_active_event.values())
        pending_events = list(group_to_pending_event.values())

        active_events.sort(key=lambda e : e.group)
        pending_events.sort(key=lambda e : e.group)

        if len(active_events) == 0 and len(pending_events) == 0:
            await self.bot.say("No events available for " + server)
            return


        output = "Events for {}".format(server)

        if len(active_events) > 0:
            output += "\n\n" + "G Remaining Dungeon"
            for e in active_events:
                output += "\n" + e.toPartialEvent(self)

        if len(pending_events) > 0:
            output += "\n\n" + "G PT    ET    ETA     Dungeon"
            for e in pending_events:
                output += "\n" + e.toPartialEvent(self)

        await self.bot.say(box(output))

def setup(bot):
    print('padevent bot setup')
    n = PadEvents(bot)
    n.registerTasks(asyncio.get_event_loop())
    bot.add_cog(n)
    print('done adding padevent bot')

def makeChannelReg(channel_id, server):
    server = normalizeServer(server)
    return {
        "channel_id": channel_id,
        "server" : server
    }

class PadEventSettings(CogSettings):
    def make_default_settings(self):
        config = {
          'guerrilla_regs' : [],
          'daily_regs' : [],
        }
        return config

    def listGuerrillaReg(self):
        return self.bot_settings['guerrilla_regs']

    def addGuerrillaReg(self, channel_id, server):
        self.listGuerrillaReg().append(makeChannelReg(channel_id, server))
        self.save_settings()

    def checkGuerrillaReg(self, channel_id, server):
        return makeChannelReg(channel_id, server) in self.listGuerrillaReg()

    def removeGuerrillaReg(self, channel_id, server):
        if self.checkGuerrillaReg(channel_id, server):
            self.listGuerrillaReg().remove(makeChannelReg(channel_id, server))
            self.save_settings()

    def listDailyReg(self):
        return self.bot_settings['daily_regs']

    def addDailyReg(self, channel_id, server):
        self.listDailyReg().append(makeChannelReg(channel_id, server))
        self.save_settings()

    def checkDailyReg(self, channel_id, server):
        return makeChannelReg(channel_id, server) in self.listDailyReg()

    def removeDailyReg(self, channel_id, server):
        if self.checkDailyReg(channel_id, server):
            self.listDailyReg().remove(makeChannelReg(channel_id, server))
            self.save_settings()
