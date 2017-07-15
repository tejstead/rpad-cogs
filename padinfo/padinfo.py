import asyncio
from builtins import filter
from collections import OrderedDict, Counter
from collections import defaultdict
import csv
from datetime import datetime
from datetime import timedelta
import difflib
from enum import Enum
import http.client
from itertools import groupby
import json
from operator import itemgetter
import os
import re
import threading
import time
import traceback
import urllib.parse

from dateutil import tz
import discord
from discord.ext import commands
import prettytable
import pytz
import romkan
from setuptools.command.alias import alias
import unidecode

from __main__ import user_allowed, send_cmd_help

from . import padguide
from .rpadutils import *
from .utils import checks
from .utils.chat_formatting import *
from .utils.cog_settings import *
from .utils.dataIO import dataIO
from .utils.twitter_stream import *


HELP_MSG = """
^helpid : shows this message
^id <query> : look up a monster and print a link to puzzledragonx
^pic <query> : Look up a monster and display its image inline

Options for <query>
    <id> : Find a monster by ID
        ^id 1234 (picks sun quan)
    <name> : Take the best guess for a monster, picks the most recent monster
        ^id kali (picks uvo d kali)
    <prefix> <name> : Limit by element or awoken, e.g.
        ^id ares  (selects the most recent, awoken ares)
        ^id aares (explicitly selects awoken ares)
        ^id a ares (spaces work too)
        ^id rd ares (select a specific evo for ares, the red/dark one)
        ^id r/d ares (slashes, spaces work too)

computed nickname list and overrides: https://docs.google.com/spreadsheets/d/1EyzMjvf8ZCQ4K-gJYnNkiZlCEsT9YYI9dUd-T5qCirc/pubhtml
submit an override suggestion: https://docs.google.com/forms/d/1kJH9Q0S8iqqULwrRqB9dSxMOMebZj6uZjECqi4t9_z0/edit"""

EMBED_NOT_GENERATED = -1


class OrderedCounter(Counter, OrderedDict):
    """Counter that remembers the order elements are first seen"""

    def __repr__(self):
        return "%s(%r)" % (self.__class_.__name__, OrderedDict(self))

    def __reduce__(self):
        return self.__class__, (OrderedDict(self),)


def dl_nicknames():
    # one hour expiry
    expiry_secs = 1 * 60 * 60
    file_url = "https://docs.google.com/spreadsheets/d/1EyzMjvf8ZCQ4K-gJYnNkiZlCEsT9YYI9dUd-T5qCirc/pub?gid=1926254248&single=true&output=csv"
    return makeCachedPlainRequest('nicknames.csv', file_url, expiry_secs)


INFO_PDX_TEMPLATE = 'http://www.puzzledragonx.com/en/monster.asp?n={}'
RPAD_PIC_TEMPLATE = 'https://storage.googleapis.com/mirubot/padimages/{}/full/{}.png'
RPAD_PORTRAIT_TEMPLATE = 'https://storage.googleapis.com/mirubot/padimages/{}/portrait/{}.png'

# This was overwritten by voltron. PDX opted to copy it +10,000 ids away
CROWS_1 = {x: x + 10000 for x in range(2601, 2635 + 1)}
# This isn't overwritten but PDX adjusted anyway
CROWS_2 = {x: x + 10000 for x in range(3460, 3481 + 1)}

PDX_JP_ADJUSTMENTS = {}
PDX_JP_ADJUSTMENTS.update(CROWS_1)
PDX_JP_ADJUSTMENTS.update(CROWS_2)


def get_pdx_url(m):
    pdx_id = m.monster_id_na
    if int(m.monster_id) == m.monster_id_jp:
        pdx_id = PDX_JP_ADJUSTMENTS.get(pdx_id, pdx_id)
    return INFO_PDX_TEMPLATE.format(pdx_id)


def get_portrait_url(m):
    if int(m.monster_id) != m.monster_id_na:
        return RPAD_PORTRAIT_TEMPLATE.format('na', m.monster_id_na)
    else:
        return RPAD_PORTRAIT_TEMPLATE.format('jp', m.monster_id_jp)


def get_pic_url(m):
    if int(m.monster_id) != m.monster_id_na:
        return RPAD_PIC_TEMPLATE.format('na', m.monster_id_na)
    else:
        return RPAD_PIC_TEMPLATE.format('jp', m.monster_id_jp)


EXPOSED_PAD_INFO = None


class PadInfo:
    def __init__(self, bot):
        self.bot = bot

        self.settings = PadInfoSettings("padinfo")

        self.nickname_text = None
        self.pginfo_all = None
        self.pginfo_na = None
        self.id_to_monster = None

        self.download_and_refresh_nicknames()

        self.menu = Menu(bot)

        global EXPOSED_PAD_INFO
        EXPOSED_PAD_INFO = self

        # These emojis are the keys into the idmenu submenus
        self.id_emoji = '\N{INFORMATION SOURCE}'
        self.evo_emoji = char_to_emoji('e')
        self.mats_emoji = char_to_emoji('m')
        self.pantheon_emoji = '\N{CLASSICAL BUILDING}'
        self.skillups_emoji = '\N{MEAT ON BONE}'
        self.pic_emoji = '\N{FRAME WITH PICTURE}'

        self.historic_lookups_file_path = "data/padinfo/historic_lookups.json"
        if not dataIO.is_valid_json(self.historic_lookups_file_path):
            print("Creating empty historic_lookups.json...")
            dataIO.save_json(self.historic_lookups_file_path, {})

        self.historic_lookups = dataIO.load_json(self.historic_lookups_file_path)

    def __unload(self):
        print("unloading padinfo")
        self.reload_nicknames_task.cancel()

        global EXPOSED_PAD_INFO
        EXPOSED_PAD_INFO = None

    def registerTasks(self, event_loop):
        print("registering tasks")
        self.reload_nicknames_task = event_loop.create_task(self.reload_nicknames())

    async def reload_nicknames(self):
        print("nickname reloader")
        first_run = True
        while "PadInfo" in self.bot.cogs:
            do_short = False
            try:
                if not first_run:
                    self.download_and_refresh_nicknames()
                first_run = False
            except Exception as e:
                traceback.print_exc()
                do_short = True
                print("caught exception while loading nicknames " + str(e))

            try:
                if do_short:
                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(60 * 60 * 4)
            except Exception as e:
                print('wut')
                traceback.print_exc()
                print("reload nickname loop caught exception " + str(e))
                raise e

        print("done reload_nicknames")

    def download_and_refresh_nicknames(self):
        """Downloads the nickname list from drive, recreates the na_only and combined monster list"""
        self.nickname_text = dl_nicknames()
        self.pginfo_all = PgDataWrapper(self.settings.groupOverride())
        self.pginfo_na = PgDataWrapper(self.settings.groupOverride(), na_only=True)

        self.pginfo_all.populateWithOverrides(self.nickname_text)
        self.pginfo_na.populateWithOverrides(self.nickname_text)

        self.id_to_monster = self.pginfo_all.id_to_monster

    async def on_ready(self):
        """ready"""
        print("started padinfo")

    @commands.command(pass_context=True)
    async def jpname(self, ctx, *, query):
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            await self.bot.say(monsterToHeader(m))
            await self.bot.say(box(m.name_jp))
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(name="id", pass_context=True)
    async def _do_id_all(self, ctx, *, query):
        await self._do_id(ctx, query)

    @commands.command(name="idna", pass_context=True)
    async def _do_id_na(self, ctx, *, query):
        await self._do_id(ctx, query, na_only=True)

    async def _do_id(self, ctx, query, na_only=False):
        m, err, debug_info = self.findMonster(query, na_only=na_only)
        if m is not None:
            await self._do_idmenu(ctx, m, self.id_emoji)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(name="idz", pass_context=True)
    async def _doidz(self, ctx, *, query):
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            info, link = monsterToInfoText(m)
            await self.bot.say(box(info) + '\n<' + link + '>')
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(name="evos", pass_context=True)
    async def evos(self, ctx, *, query):
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            await self._do_idmenu(ctx, m, self.evo_emoji)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(name="mats", pass_context=True, aliases=['evomats', 'evomat'])
    async def evomats(self, ctx, *, query):
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            await self._do_idmenu(ctx, m, self.mats_emoji)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(pass_context=True)
    async def pantheon(self, ctx, *, query):
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            menu = await self._do_idmenu(ctx, m, self.pantheon_emoji)
            if menu == EMBED_NOT_GENERATED:
                await self.bot.say(inline('Not a pantheon monster'))
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(pass_context=True)
    async def skillups(self, ctx, *, query):
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            menu = await self._do_idmenu(ctx, m, self.skillups_emoji)
            if menu == EMBED_NOT_GENERATED:
                await self.bot.say(inline('No skillups available'))
        else:
            await self.bot.say(self.makeFailureMsg(err))

#     async def _do_idmenu(self, ctx, m : Monster, starting_menu_emoji):
    async def _do_idmenu(self, ctx, m, starting_menu_emoji):
        id_embed = monsterToEmbed(m, self.get_emojis())
        evo_embed = monsterToEvoEmbed(m)
        mats_embed = monsterToEvoMatsEmbed(m)
        pic_embed = monsterToPicEmbed(m)

        emoji_to_embed = OrderedDict()
        emoji_to_embed[self.id_emoji] = id_embed
        emoji_to_embed[self.evo_emoji] = evo_embed
        emoji_to_embed[self.mats_emoji] = mats_embed
        emoji_to_embed[self.pic_emoji] = pic_embed

        pantheon_embed = monsterToPantheonEmbed(m, self.pginfo_all)
        if pantheon_embed:
            emoji_to_embed[self.pantheon_emoji] = pantheon_embed

        skillups_embed = monsterToSkillupsEmbed(m, self.pginfo_all)
        if skillups_embed:
            emoji_to_embed[self.skillups_emoji] = skillups_embed

        remove_emoji = self.menu.emoji['no']
        emoji_to_embed[remove_emoji] = self.menu.reaction_delete_message

        if starting_menu_emoji not in emoji_to_embed:
            # Selected menu wasn't generated for this monster
            return EMBED_NOT_GENERATED

        try:
            result_msg, result_embed = await self.menu.custom_menu(ctx, emoji_to_embed, starting_menu_emoji, timeout=30)
            if result_msg and result_embed:
                # Message is finished but not deleted, clear the footer
                result_embed.set_footer(text=discord.Embed.Empty)
                await self.bot.edit_message(result_msg, embed=result_embed)
        except Exception as ex:
            print('Menu failure', ex)

    @commands.command(pass_context=True)
    @checks.mod_or_permissions(manage_server=True)
    async def debugid(self, ctx, *, query):
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            info, link = monsterToInfoText(m)
            await self.bot.say(box(info))
            await self.bot.say(box('Lookup type: ' + debug_info + '\nMonster info: ' + m.debug_info))
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(pass_context=True, aliases=['img'])
    async def pic(self, ctx, *, query):
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            await self._do_idmenu(ctx, m, self.pic_emoji)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(pass_context=True, aliases=['leaders', 'leaderskills', 'ls'])
    async def leaderskill(self, ctx, left_query, right_query=None, *, bad=None):
        """Display the multiplier and leaderskills for two monsters.

        If either your left or right query contains spaces, wrap in quotes.
        e.g.: ^leaderskill "r sonia" "b sonia"
        """
        if bad:
            await self.bot.say(inline('Too many inputs. Try wrapping your queries in quotes.'))
            return

        left_m, left_err, _ = self.findMonster(left_query)
        if right_query:
            right_m, right_err, _ = self.findMonster(right_query)
        else:
            right_m, right_err, = left_m, left_err

        err_msg = '{} query failed to match a monster: [ {} ]. If your query is multiple words, wrap it in quotes.'
        if left_err:
            await self.bot.say(inline(err_msg.format('Left', left_query)))
            return
        if right_err:
            await self.bot.say(inline(err_msg.format('Right', right_query)))
            return

        lhp, latk, lrcv, lresist = left_m.leader_skill_data.getMaxMultipliers()
        rhp, ratk, rrcv, rresist = right_m.leader_skill_data.getMaxMultipliers()
        multiplier_text = createMultiplierText(lhp, latk, lrcv, lresist, rhp, ratk, rrcv, rresist)

        embed = discord.Embed()
        embed.title = 'Multiplier [{}]\n\n'.format(multiplier_text)
        description = ''
        description += '\n**' + \
            monsterToHeader(left_m, link=True) + '**\n' + (left_m.leader_text or 'None/Missing')
        description += '\n**' + \
            monsterToHeader(right_m, link=True) + '**\n' + (right_m.leader_text or 'None/Missing')
        embed.description = description
        await self.bot.say(embed=embed)

    @commands.command(name="helpid", pass_context=True, aliases=['helppic', 'helpimg'])
    async def _helpid(self, ctx):
        await self.bot.whisper(box(HELP_MSG))

    @commands.group(pass_context=True)
    async def padinfo(self, ctx):
        """PAD info management"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @padinfo.command(pass_context=True)
    @checks.is_owner()
    async def addgroupoverride(self, ctx, monster_id: int, nickname: str):
        m = self.id_to_monster[monster_id]
        self.settings.addGroupOverride(monster_id, nickname)
        output = 'mapped tree for No. {} {} to {}'.format(m.monster_id_na, m.name_na, nickname)
        await self.bot.say(inline(output))

    @padinfo.command(pass_context=True)
    @checks.is_owner()
    async def rmgroupoverride(self, ctx, monster_id: int):
        if self.settings.checkGroupOverride(monster_id):
            self.settings.removeGroupOverride(monster_id)
            await self.bot.say(inline('Done'))
        else:
            await self.bot.say(inline('Not an override'))

    @padinfo.command(pass_context=True)
    @checks.is_owner()
    async def listgroupoverride(self, ctx):
        output = 'Monster Overrides:\n'
        for id, override in self.settings.groupOverride().items():
            m = self.id_to_monster[int(id)]
            output += '\t {} -> No. {} {}\n'.format(override, m.monster_id_na, m.name_na)
        await self.bot.say(box(output))

    @padinfo.command(pass_context=True)
    @checks.is_owner()
    async def setemojiservers(self, ctx, *, emoji_servers=''):
        """Set the emoji servers by ID (csv)"""
        self.settings.emojiServers().clear()
        if emoji_servers:
            self.settings.setEmojiServers(emoji_servers.split(','))
        await self.bot.say(inline('Set {} servers'.format(len(self.settings.emojiServers()))))

    def get_emojis(self):
        server_ids = self.settings.emojiServers()
        return [e for s in self.bot.servers if s.id in server_ids for e in s.emojis]

    def makeFailureMsg(self, err):
        msg = 'Lookup failed: ' + err + '.\n'
        msg += 'Try one of <id>, <name>, [argbld]/[rgbld] <name>. Unexpected results? Use ^helpid for more info.'
        return box(msg)

    def findMonster(self, query, na_only=False):
        query = rmdiacritics(query)
        m, err, debug_info = self._findMonster(query, na_only)

        monster_id = m.monster_id if m else -1
        self.historic_lookups[query] = monster_id
        dataIO.save_json(self.historic_lookups_file_path, self.historic_lookups)

        return m, err, debug_info

    def _findMonster(self, query, na_only=False):
        query = query.lower().strip()

        # id search
        if query.isdigit():
            m = self.id_to_monster.get(int(query))
            if m is None:
                return None, 'Looks like a monster ID but was not found', None
            else:
                return m, None, "ID lookup"
            # special handling for na/jp

        pginfo = self.pginfo_na if na_only else self.pginfo_all

        # handle exact nickname match
        if query in pginfo.all_entries:
            return pginfo.all_entries[query], None, "Exact nickname"

        if len(query) < 2 and containsJp(query):
            return None, 'Japanese queries must be at least 2 characters', None
        elif len(query) < 4 and not containsJp(query):
            return None, 'Your query must be at least 4 letters', None

        # TODO: this should be a length-limited priority queue
        matches = set()
        # prefix search for nicknames, space-preceeded, take max id
        for nickname, m in pginfo.all_entries.items():
            if nickname.startswith(query + ' '):
                matches.add(m)
        if len(matches):
            return pickBestMonster(matches), None, "Space nickname prefix, max of {}".format(len(matches))

        # prefix search for nicknames, take max id
        for nickname, m in pginfo.all_entries.items():
            if nickname.startswith(query):
                matches.add(m)
        if len(matches):
            all_names = ",".join(map(lambda x: x.name_na, matches))
            return pickBestMonster(matches), None, "Nickname prefix, max of {}, matches=({})".format(len(matches), all_names)

        # prefix search for full name, take max id
        for nickname, m in pginfo.all_entries.items():
            if (m.name_na.lower().startswith(query) or m.name_jp.lower().startswith(query)):
                matches.add(m)
        if len(matches):
            return pickBestMonster(matches), None, "Full name, max of {}".format(len(matches))

        # for nicknames with 2 names, prefix search 2nd word, take max id
        if query in pginfo.two_word_entries:
            return pginfo.two_word_entries[query], None, "Second-word nickname prefix, max of {}".format(len(matches))

        # TODO: refactor 2nd search characteristcs for 2nd word

        # full name contains on nickname, take max id
        for nickname, m in pginfo.all_entries.items():
            if (query in m.name_na.lower() or query in m.name_jp.lower()):
                matches.add(m)
        if len(matches):
            return pickBestMonster(matches), None, 'Full name match on nickname, max of {}'.format(len(matches))

        # full name contains on full monster list, take max id

        for m in pginfo.full_monster_list:
            if (query in m.name_na.lower() or query in m.name_jp.lower()):
                matches.add(m)
        if len(matches):
            return pickBestMonster(matches), None, 'Full name match on full list, max of {}'.format(len(matches))

        # No decent matches. Try near hits on nickname instead
        matches = difflib.get_close_matches(query, pginfo.all_entries.keys(), n=1, cutoff=.8)
        if len(matches):
            return pginfo.all_entries[matches[0]], None, 'Close nickname match'

        # Still no decent matches. Try near hits on full name instead
        def get_na_name(m): return m.name_na.lower()
        na_name_map = {m.name_na.lower(): m for m in pginfo.full_monster_list}
        matches = difflib.get_close_matches(query, na_name_map.keys(), n=1, cutoff=.9)
        if len(matches):
            return na_name_map[matches[0]], None, 'Close name match'

        # couldn't find anything
        return None, "Could not find a match for: " + query, None

    def map_awakenings_text(self, m):
        """Exported for use in other cogs"""
        return _map_awakenings_text(m)


def pickBestMonster(monster_list):
    return max(monster_list, key=lambda x: (x.selection_priority, x.rarity, x.monster_id_na))


def setup(bot):
    print('padinfo bot setup')
    n = PadInfo(bot)
    n.registerTasks(asyncio.get_event_loop())
    bot.add_cog(n)
    print('done adding padinfo bot')


class PadInfoSettings(CogSettings):
    def make_default_settings(self):
        config = {}
        return config

    def groupOverride(self):
        if 'group_override' not in self.bot_settings:
            self.bot_settings['group_override'] = {}
        return self.bot_settings['group_override']

    def addGroupOverride(self, monster_id, nickname):
        monster_id = str(monster_id)
        self.groupOverride()[monster_id] = nickname
        self.save_settings()

    def checkGroupOverride(self, monster_id):
        monster_id = str(monster_id)
        return monster_id in self.groupOverride().keys()

    def removeGroupOverride(self, monster_id):
        monster_id = str(monster_id)
        if self.checkGroupOverride(monster_id):
            self.groupOverride().pop(monster_id)
            self.save_settings()

    def emojiServers(self):
        key = 'emoji_servers'
        if key not in self.bot_settings:
            self.bot_settings[key] = []
        return self.bot_settings[key]

    def setEmojiServers(self, emoji_servers):
        es = self.emojiServers()
        es.clear()
        es.extend(emoji_servers)
        self.save_settings()


HIGH_SELECTION_PRIORITY = 2
LOW_SELECTION_PRIORITY = 1
UNKNOWN_SELECTION_PRIORITY = 0


class Monster:
    def __init__(self,
                 base_monster,
                 monster_info,
                 additional_info,
                 awakening_skills,
                 evos,
                 active_skill,
                 leader_skill,
                 leader_skill_data,
                 type_map,
                 attribute_map,
                 drop_info_list,
                 series,
                 monster_price,
                 mats_to_evo,
                 used_for_evo,
                 monster_ids_with_skill,
                 cur_evo):

        self.monster_id = base_monster.monster_id
        # NA is used in puzzledragonx
        self.monster_id_na = base_monster.monster_id_na
        self.monster_id_jp = base_monster.monster_id_jp
        self.series_name = series.name

        self.debug_info = ''
        self.selection_priority = UNKNOWN_SELECTION_PRIORITY

        self.evo_to = [x.to_monster_id for x in evos]
        self.evo_from = list()

        self.awakening_names = [x.name for x in awakening_skills]

        self.hp = int(base_monster.hp)
        self.atk = int(base_monster.atk)
        self.rcv = int(base_monster.rcv)
        self.weighted_stats = int(self.hp / 10 + self.atk / 5 + self.rcv / 3)

        self.rarity = int(base_monster.rarity)
        self.cost = int(base_monster.cost)
        self.max_level = int(base_monster.max_level)

        self.name_na = rmdiacritics(base_monster.name_na)
        self.name_jp = base_monster.name_jp

        self.on_us = monster_info.on_us == '1'
        self.on_na = monster_info.on_us == '1'
        self.series_id = monster_info.series_id
        self.is_gfe = self.series_id == '34'
        self.in_pem = monster_info.in_pem == '1'
        self.in_rem = monster_info.in_rem == '1'
        self.pem_evo = self.in_pem
        self.rem_evo = self.in_rem

        self.roma_subname = None
        if self.name_jp == self.name_na and containsJp(self.name_na):
            subname = self.name_jp.replace('＝', '')
            adjusted_subname = ''
            for part in subname.split('・'):
                roma_part = romkan.to_roma(part)
                roma_part_undiecode = unidecode.unidecode(part)

                if part != roma_part and not containsJp(roma_part):
                    adjusted_subname += ' ' + roma_part.strip('-')
            adjusted_subname = adjusted_subname.strip()
            if adjusted_subname:
                self.roma_subname = adjusted_subname
                self.debug_info += '| roma: ' + adjusted_subname

        self.attr1 = None
        self.attr2 = None
        if base_monster.attr1 != '0':
            self.attr1 = attribute_map[base_monster.attr1].name
        if base_monster.attr2 != '0':
            self.attr2 = attribute_map[base_monster.attr2].name

        self.type1 = None
        self.type2 = None
        self.type3 = None
        if base_monster.type1 != '0':
            self.type1 = type_map[base_monster.type1].name
        if base_monster.type2 != '0':
            self.type2 = type_map[base_monster.type2].name
        if additional_info and additional_info.sub_type != '0':
            self.type3 = type_map[additional_info.sub_type].name

        self.active_skill = active_skill
        self.server_actives = {}
        self.server_skillups = {}

        self.leader_text = None
        if leader_skill:
            self.leader_text = leader_skill.desc

        self.leader_skill_data = leader_skill_data or padguide.EMPTY_SKILL_LEADER_DATA
        hp, atk, rcv, resist = self.leader_skill_data.getMaxMultipliers()
        self.multiplier_text = createMultiplierText(hp, atk, rcv, resist, hp, atk, rcv, resist)

        self.farmable = len(drop_info_list) > 0
        self.farmable_evo = self.farmable
        self.drop_info_list = drop_info_list

        self.buy_mp = monster_price.buy_mp
        self.in_mpshop = self.buy_mp > 0
        self.sell_mp = monster_price.sell_mp

        assist_setting = additional_info.extra_val_1 if additional_info else None
        if assist_setting == '1':
            self.is_inheritable = True
        elif assist_setting == '2':
            self.is_inheritable = False
        else:
            self.is_inheritable = len(
                self.awakening_names) > 0 and self.rarity >= 5 and self.sell_mp > 3000

        self.alt_evos = list()

        self.mats_to_evo = [x.monster_id for x in sorted(mats_to_evo, key=lambda z: z.order)]
        self.used_for_evo = used_for_evo

        self.monster_ids_with_skill = monster_ids_with_skill
        self.monsters_with_skill = list()

        self.evo_type = cur_evo.tv_type if cur_evo else None


def monsterToInfoText(m: Monster):
    header = monsterToHeader(m)

    if m.roma_subname:
        header += ' [{}]'.format(m.roma_subname)

    if not m.on_us:
        header += ' (JP only)'

    info_row = m.attr1
    if m.attr2:
        info_row += '/' + m.attr2

    info_row += '  |  ' + m.type1
    if m.type2:
        info_row += '/' + m.type2
    if m.type3:
        info_row += '/' + m.type3

    info_row += '  |  Rarity:' + str(m.rarity)
    info_row += '  |  Cost:' + str(m.cost)

    killers = compute_killers(m.type1, m.type2, m.type3)
    if killers:
        info_row += '  |  Avail. Killers: ' + '/'.join(killers)

    stats_row = 'Lv. {}  HP {}  ATK {}  RCV {}  Weighted {}'.format(
        m.max_level, m.hp, m.atk, m.rcv, m.weighted_stats)

    awakenings_row = _map_awakenings_text(m)

    ls_row = 'LS: ' + (m.leader_text or 'None/Missing')

    active_row = 'AS: '
    if m.active_skill:
        active_row += '({}->{}): {}'.format(m.active_skill.turn_max,
                                            m.active_skill.turn_min, m.active_skill.desc)
    else:
        active_row += 'None/Missing'

    info_chunk = '{}\n{}\n{}\n{}\n{}\n{}'.format(
        header, info_row, stats_row, awakenings_row, ls_row, active_row)
    link_row = get_pdx_url(m)

    return info_chunk, link_row


def monsterToHeader(m: Monster, link=False):
    msg = 'No. {} {}'.format(m.monster_id_na, m.name_na)
    return '[{}]({})'.format(msg, get_pdx_url(m)) if link else msg


def monsterToJpSuffix(m: Monster):
    suffix = ""
    if m.roma_subname:
        suffix += ' [{}]'.format(m.roma_subname)
    if not m.on_us:
        suffix += ' (JP only)'
    return suffix


def monsterToLongHeader(m: Monster, link=False):
    msg = monsterToHeader(m) + monsterToJpSuffix(m)
    return '[{}]({})'.format(msg, get_pdx_url(m)) if link else msg


def monsterToLongHeaderWithAttr(m: Monster, link=False):
    header = 'No. {} {} {}'.format(
        m.monster_id_na,
        "({}{})".format(attr_prefix_map[m.attr1], "/" +
                        attr_prefix_map[m.attr2] if m.attr2 else ""),
        m.name_na)
    msg = header + monsterToJpSuffix(m)
    return '[{}]({})'.format(msg, get_pdx_url(m)) if link else msg


def monsterToEvoText(m: Monster):
    output = monsterToLongHeader(m)
    for ae in sorted(m.alt_evos, key=lambda x: int(x.monster_id)):
        output += "\n\t- {}".format(monsterToLongHeader(ae))
    return output


def monsterToThumbnailUrl(m: Monster):
    return get_portrait_url(m)


def monsterToBaseEmbed(m: Monster):
    header = monsterToLongHeader(m)
    embed = discord.Embed()
    embed.set_thumbnail(url=monsterToThumbnailUrl(m))
    embed.title = header
    embed.url = get_pdx_url(m)
    embed.set_footer(text='Requester may click the reactions below to switch tabs')
    return embed


def monsterToEvoEmbed(m: Monster):
    embed = monsterToBaseEmbed(m)

    if not len(m.alt_evos):
        embed.description = 'No alternate evos'
        return embed

    field_name = '{} alternate evos'.format(len(m.alt_evos))
    field_data = ''
    for ae in sorted(m.alt_evos, key=lambda x: int(x.monster_id)):
        field_data += "{}\n".format(monsterToLongHeader(ae, link=True))

    embed.add_field(name=field_name, value=field_data)

    return embed


def monsterToEvoMatsEmbed(m: Monster):
    embed = monsterToBaseEmbed(m)

    mats_to_evo_size = len(m.mats_to_evo)
    used_for_evo_size = len(m.used_for_evo)

    field_name = 'Evo materials'
    field_data = ''
    if mats_to_evo_size:
        for ae in m.mats_to_evo:
            field_data += "{}\n".format(monsterToLongHeader(ae, link=True))
    else:
        field_data = 'None'
    embed.add_field(name=field_name, value=field_data)

    if not used_for_evo_size:
        return embed

    field_name = 'Material for'
    field_data = ''
    if used_for_evo_size > 5:
        field_data = '{} monsters'.format(used_for_evo_size)
    else:
        item_count = min(used_for_evo_size, 5)
        for ae in sorted(m.used_for_evo, key=lambda x: x.monster_id_na, reverse=True)[:item_count]:
            field_data += "{}\n".format(monsterToLongHeader(ae, link=True))
    embed.add_field(name=field_name, value=field_data)

    return embed


def monsterToPantheonEmbed(m: Monster, pginfo):
    # def monsterToPantheonEmbed(m : Monster, pginfo : PgDataWrapper):
    pantheon_list = pginfo.series_id_to_monsters.get(m.series_id, [])
    if len(pantheon_list) == 0 or len(pantheon_list) > 6:
        return None

    embed = monsterToBaseEmbed(m)

    field_name = 'Pantheon: ' + m.series_name
    field_data = ''
    for monster in sorted(pantheon_list, key=lambda x: x.monster_id_na):
        field_data += '\n' + monsterToHeader(monster, link=True)
    embed.add_field(name=field_name, value=field_data)

    return embed


def monsterToSkillupsEmbed(m: Monster, pginfo):
    # def monsterToSkillupsEmbed(m : Monster, pginfo : PgDataWrapper):
    skillups_list = m.monsters_with_skill
    if len(skillups_list) + len(m.server_actives) == 0:
        return None

    embed = monsterToBaseEmbed(m)

    skillups_to_skip = list()
    for server, skillup in m.server_skillups.items():
        skillup_header = 'Skillup in ' + server
        skillup_body = monsterToHeader(skillup, link=True)
        embed.add_field(name=skillup_header, value=skillup_body)
        skillups_to_skip.append(skillup.monster_id_na)

    field_name = 'Skillups'
    field_data = ''
    for monster in sorted(skillups_list, key=lambda x: x.monster_id_na):
        if monster.monster_id_na in skillups_to_skip:
            continue
        field_data += '\n' + monsterToHeader(monster, link=True)

    if len(field_data.strip()):
        embed.add_field(name=field_name, value=field_data)

    return embed


def monsterToPicUrl(m: Monster):
    return get_pic_url(m)


def monsterToPicEmbed(m: Monster):
    # def monsterToSkillupsEmbed(m : Monster, pginfo : PgDataWrapper):
    embed = monsterToBaseEmbed(m)
    url = monsterToPicUrl(m)
    embed.set_image(url=url)
    # Clear the thumbnail, don't need it on pic
    embed.set_thumbnail(url='')
    return embed


def monsterToTypeString(m: Monster):
    output = m.type1
    if m.type2:
        output += '/' + m.type2
    if m.type3:
        output += '/' + m.type3
    return output


def monsterToAcquireString(m: Monster):
    acquire_text = None
    if m.farmable and not m.mp_evo:
        # Some MP shop monsters 'drop' in PADR
        acquire_text = 'Farmable'
    elif m.farmable_evo and not m.mp_evo:
        acquire_text = 'Farmable Evo'
    elif m.in_pem:
        acquire_text = 'In PEM'
    elif m.pem_evo:
        acquire_text = 'PEM Evo'
    elif m.in_rem:
        acquire_text = 'In REM'
    elif m.rem_evo:
        acquire_text = 'REM Evo'
    elif m.in_mpshop:
        acquire_text = 'MP Shop'
    elif m.mp_evo:
        acquire_text = 'MP Shop Evo'
    return acquire_text


def match_emoji(emoji_list, name):
    for e in emoji_list:
        if e.name == name:
            return e
    return None


def monsterToEmbed(m: Monster, emoji_list):
    embed = monsterToBaseEmbed(m)

    info_row_1 = monsterToTypeString(m)
    acquire_text = monsterToAcquireString(m)

    info_row_2 = '**Rarity** {}\n**Cost** {}'.format(m.rarity, m.cost)
    if acquire_text:
        info_row_2 += '\n**{}**'.format(acquire_text)
    if m.is_inheritable:
        info_row_2 += '\n**Inheritable**'

    embed.add_field(name=info_row_1, value=info_row_2)

    stats_row_1 = 'Weighted {}'.format(m.weighted_stats)
    stats_row_2 = '**HP** {}\n**ATK** {}\n**RCV** {}'.format(m.hp, m.atk, m.rcv)
    embed.add_field(name=stats_row_1, value=stats_row_2)

    awakenings_row = ''
    for a in m.awakening_names:
        mapped_awakening = AWAKENING_NAME_MAP_RPAD.get(a, a)
        mapped_awakening = match_emoji(emoji_list, mapped_awakening)

        if mapped_awakening is None:
            mapped_awakening = AWAKENING_NAME_MAP.get(a, a)

        awakenings_row += ' {}'.format(mapped_awakening)

    awakenings_row = awakenings_row.strip()

    if not len(awakenings_row):
        awakenings_row = 'No Awakenings'

    killers = compute_killers(m.type1, m.type2, m.type3)
    killers_row = '**Available Killers:** {}'.format(' '.join(killers))

    embed.description = '{}\n{}'.format(awakenings_row, killers_row)

    if len(m.server_actives) >= 2:
        for server, active in m.server_actives.items():
            active_header = '({} Server) Active Skill ({} -> {})'.format(server,
                                                                         active.turn_max, active.turn_min)
            active_body = active.desc
            embed.add_field(name=active_header, value=active_body, inline=False)
    else:
        active_header = 'Active Skill'
        active_body = 'None/Missing'
        if m.active_skill:
            active_header = 'Active Skill ({} -> {})'.format(m.active_skill.turn_max,
                                                             m.active_skill.turn_min)
            active_body = m.active_skill.desc
        embed.add_field(name=active_header, value=active_body, inline=False)

    ls_row = m.leader_text if m.leader_text else 'None/Missing'
    ls_header = 'Leader Skill'
    if m.multiplier_text:
        ls_header += " [ {} ]".format(m.multiplier_text)
    embed.add_field(name=ls_header, value=ls_row, inline=False)

    return embed


attr_prefix_map = {
    'Fire': 'r',
    'Water': 'b',
    'Wood': 'g',
    'Light': 'l',
    'Dark': 'd',
}

attr_prefix_long_map = {
    'Fire': 'red',
    'Water': 'blue',
    'Wood': 'green',
    'Light': 'light',
    'Dark': 'dark',
}


def compute_killers(*types):
    if 'Balance' in types:
        return ['Any']
    killers = set()
    for t in types:
        killers.update(type_to_killers_map.get(t, []))
    return sorted(killers)


type_to_killers_map = {
    'God': ['Devil'],
    'Devil': ['God'],
    'Machine': ['God', 'Balance'],
    'Dragon': ['Machine', 'Healer'],
    'Physical': ['Machine', 'Healer'],
    'Attacker': ['Devil', 'Physical'],
    'Healer': ['Dragon', 'Attacker'],
}

series_to_prefix_map = {
    '130': ['halloween'],
    '136': ['xmas', 'christmas'],
    '125': ['summer', 'beach'],
    '114': ['school', 'academy', 'gakuen'],
    '139': ['new years', 'ny'],
    '149': ['wedding', 'bride'],
    '154': ['padr'],
}

AWAKENING_NAME_MAP_RPAD = {
    'Enhanced Attack': 'boost_atk',
    'Enhanced HP': 'boost_hp',
    'Enhanced Heal': 'boost_rcv',

    'God Killer': 'killer_god',
    'Dragon Killer': 'killer_dragon',
    'Devil Killer': 'killer_devil',
    'Machine Killer': 'killer_machine',
    'Balanced Killer': 'killer_balance',
    'Attacker Killer': 'killer_attacker',

    'Physical Killer': 'killer_physical',
    'Healer Killer': 'killer_healer',
    'Evolve Material Killer': 'killer_evomat',
    'Awaken Material Killer': 'killer_awoken',
    'Enhance Material Killer': 'killer_enhancemat',
    'Vendor Material Killer': 'killer_vendor',

    'Auto-Recover': 'misc_autoheal',
    'Recover Bind': 'misc_bindclear',
    'Enhanced Combo': 'misc_comboboost',
    'Guard Break': 'misc_guardbreak',
    'Multi Boost': 'misc_multiboost',
    'Additional Attack': 'misc_extraattack',
    'Skill Boost': 'misc_sb',
    'Extend Time': 'misc_te',
    'Two-Pronged Attack': 'misc_tpa',

    'Enhanced Fire Orbs': 'oe_fire',
    'Enhanced Water Orbs': 'oe_water',
    'Enhanced Wood Orbs': 'oe_wood',
    'Enhanced Light Orbs': 'oe_light',
    'Enhanced Dark Orbs': 'oe_dark',
    'Enhanced Heal Orbs': 'oe_heart',

    'Reduce Fire Damage': 'reduce_fire',
    'Reduce Water Damage': 'reduce_water',
    'Reduce Wood Damage': 'reduce_wood',
    'Reduce Light Damage': 'reduce_light',
    'Reduce Dark Damage': 'reduce_dark',

    'Resistance-Bind': 'res_bind',
    'Resistance-Dark': 'res_blind',
    'Resistance-Jammers': 'res_jammer',
    'Resistance-Poison': 'res_poison',
    'Resistance-Skill Bind': 'res_skillbind',

    'Enhanced Fire Att.': 'row_fire',
    'Enhanced Water Att.': 'row_water',
    'Enhanced Wood Att.': 'row_wood',
    'Enhanced Light Att.': 'row_light',
    'Enhanced Dark Att.': 'row_dark',
}

AWAKENING_NAME_MAP = {
    'Enhanced Fire Orbs': 'R-OE',
    'Enhanced Water Orbs': 'B-OE',
    'Enhanced Wood Orbs': 'G-OE',
    'Enhanced Light Orbs': 'L-OE',
    'Enhanced Dark Orbs': 'D-OE',
    'Enhanced Heal Orbs': 'H-OE',

    'Enhanced Fire Att.': 'R-RE',
    'Enhanced Water Att.': 'B-RE',
    'Enhanced Wood Att.': 'G-RE',
    'Enhanced Light Att.': 'L-RE',
    'Enhanced Dark Att.': 'D-RE',

    'Enhanced HP': 'HP',
    'Enhanced Attack': 'ATK',
    'Enhanced Heal': 'RCV',

    'Auto-Recover': 'AUTO-RECOVER',
    'Skill Boost': 'SB',
    'Resistance-Skill Bind': 'SBR',
    'Two-Pronged Attack': 'TPA',
    'Multi Boost': 'MULTI-BOOST',
    'Recover Bind': 'RCV-BIND',
    'Extend Time': 'TE',
    'Enhanced Combo': 'COMBO-BOOST',
    'Guard Break': 'DEF-BREAK',
    'Additional Attack': 'EXTRA-ATK',

    'Resistance-Bind': 'RES-BIND',
    'Resistance-Dark': 'RES-BLIND',
    'Resistance-Poison': 'RES-POISON',
    'Resistance-Jammers': 'RES-JAMMER',

    'Reduce Fire Damage': 'R-RES',
    'Reduce Water Damage': 'B-RES',
    'Reduce Wood Damage': 'G-RES',
    'Reduce Light Damage': 'L-RES',
    'Reduce Dark Damage': 'D-RES',

    'Healer Killer': 'K-HEALER',
    'Machine Killer': 'K-MACHINE',
    'Dragon Killer': 'K-DRAGON',
    'Attacker Killer': 'K-ATTACKER',
    'Physical Killer': 'K-PHYSICAL',
    'God Killer': 'K-GOD',
    'Devil Killer': 'K-DEVIL',
    'Balance Killer': 'K-BALANCE',
}


def addNickname(m: Monster):
    nickname = m.name_na.lower()
    if ',' in nickname:
        name_parts = nickname.split(',')
        if name_parts[1].strip().startswith('the '):
            # handle names like 'xxx, the yyy' where xxx is the name
            nickname = name_parts[0]
        else:
            # otherwise, grab the chunk after the last comma
            nickname = name_parts[-1]

    if 'awoken' in nickname:
        nickname = nickname.replace('awoken', '')

    m.nickname = nickname.strip()


def addPrefixes(m: Monster):
    prefixes = set()

    attr1 = attr_prefix_map[m.attr1]
    prefixes.add(attr1)

    # Add long color names like red/blue
    long_attr = attr_prefix_long_map[m.attr1]
    prefixes.add(long_attr)

    # Add long attr names like fire/water
    prefixes.add(m.attr1.lower())

    if m.attr2 is not None:
        attr2 = attr_prefix_map[m.attr2]
        prefixes.add(attr1 + attr2)
        prefixes.add(attr1 + '/' + attr2)

    # TODO add prefixes based on type

    if m.name_na.lower() == m.name_na and m.name_na != m.name_jp:
        prefixes.add('chibi')

    awoken_or_revo = False
    if 'awoken' in m.name_na.lower() or '覚醒' in m.name_na:
        awoken_or_revo = True
        prefixes.add('a')
        prefixes.add('awoken')

    if 'reincarnated' in m.name_na.lower() or '転生' in m.name_na:
        awoken_or_revo = True
        prefixes.add('revo')
        prefixes.add('reincarnated')

    if not awoken_or_revo:
        if m.evo_type is None:
            prefixes.add('base')
        elif m.evo_type == '0':
            prefixes.add('evo')
        elif m.evo_type == '1':
            prefixes.add('uvo')
            prefixes.add('uevo')
        elif m.evo_type == '2':
            prefixes.add('uuvo')
            prefixes.add('uuevo')

    # Add collab prefixes
    if m.series_id in series_to_prefix_map:
        prefixes.update(series_to_prefix_map[m.series_id])

    m.prefixes = prefixes
    m.debug_info += ' | Prefixes ({})'.format(','.join(prefixes))


class MonsterGroup:
    def __init__(self):
        self.nickname = None
        self.monsters = list()

    def computeNickname(self):
        def get_nickname(x): return x.nickname
        sorted_monsters = sorted(self.monsters, key=get_nickname)
        grouped = [(c, len(list(cgen))) for c, cgen in groupby(sorted_monsters, get_nickname)]
        best_tuple = max(grouped, key=itemgetter(1))
        self.nickname = best_tuple[0]
        for m in self.monsters:
            m.original_nickname = m.nickname
            m.nickname = self.nickname
            m.debug_info += ' | Original NN ({}) | Final NN ({})'.format(
                m.original_nickname, m.nickname)

    def overrideNickname(self, nickname):
        for m in self.monsters:
            m.original_nickname = m.nickname
            m.nickname = nickname
            m.debug_info += ' | Original NN ({}) | Override NN ({})'.format(
                m.original_nickname, m.nickname)


class PgDataWrapper:
    def __init__(self, group_overrides, na_only=False):
        attribute_list = padguide.loadJsonToItem('attributeList.jsp', padguide.PgAttribute)
        awoken_list = padguide.loadJsonToItem('awokenSkillList.jsp', padguide.PgAwakening)
        evolution_list = padguide.loadJsonToItem('evolutionList.jsp', padguide.PgEvo)
        evolution_mat_list = padguide.loadJsonToItem('evoMaterialList.jsp', padguide.PgEvoMaterial)
        monster_add_info_list = padguide.loadJsonToItem(
            'monsterAddInfoList.jsp', padguide.PgMonsterAddInfo)
        monster_info_list = padguide.loadJsonToItem('monsterInfoList.jsp', padguide.PgMonsterInfo)
        base_monster_list = padguide.loadJsonToItem('monsterList.jsp', padguide.PgBaseMonster)
        skill_list = padguide.loadJsonToItem('skillList.jsp', padguide.PgSkill)
        skill_leader_data_list = padguide.loadJsonToItem(
            'skillLeaderDataList.jsp', padguide.PgSkillLeaderData)
        type_list = padguide.loadJsonToItem('typeList.jsp', padguide.PgType)
        series_list = padguide.loadJsonToItem('seriesList.jsp', padguide.PgSeries)
        mp_list = padguide.loadJsonToItem('monsterPriceList.jsp', padguide.PgMonsterPrice)

        dungeon_monster_list = padguide.loadJsonToItem(
            'dungeonMonsterList.jsp', padguide.PgDungeonMonster)
        dungeon_monster_drop_list = padguide.loadJsonToItem(
            'dungeonMonsterDropList.jsp', padguide.PgDungeonMonsterDrop)
        dungeon_list = padguide.loadJsonToItem('dungeonList.jsp', padguide.PgDungeon)

        attribute_map = {x.attribute_id: x for x in attribute_list}

        monster_awoken_multimap = defaultdict(list)
        for item in awoken_list:
            monster_awoken_multimap[item.monster_id].append(item)

#         monster_for_evo_multimap = dict()
#         monster_for_evo_multimap[item.to_monster_id] = item

        monster_to_current_evo_item = {x.to_monster_id: x for x in evolution_list}
        evo_id_to_monster_id = {x.evo_id: x.to_monster_id for x in evolution_list}

        monster_id_to_evo_multimap = defaultdict(list)
        for item in evolution_list:
            monster_id_to_evo_multimap[item.monster_id].append(item)

        monster_evo_to_mat_multimap = defaultdict(list)
        monster_mat_id_to_evod_monster_id_multimap = defaultdict(list)
        for item in evolution_mat_list:
            monster_evo_to_mat_multimap[item.evo_id].append(item)
            evo_monster_id = evo_id_to_monster_id[item.evo_id]
            if evo_monster_id != '0':
                # Not sure what this error case is
                monster_mat_id_to_evod_monster_id_multimap[item.monster_id].append(evo_monster_id)

        monster_add_info_map = {x.monster_id: x for x in monster_add_info_list}
        monster_info_map = {x.monster_id: x for x in monster_info_list}
        skill_map = {x.skill_id: x for x in skill_list}
        skill_leader_data_map = {x.leader_id: x for x in skill_leader_data_list}
        type_map = {x.type_id: x for x in type_list}
        series_map = {x.series_id: x for x in series_list}
        monster_id_to_monster_price = {x.monster_id: x for x in mp_list}

        monster_id_to_drop_info_list = self.computeMonsterDropInfoCombined(
            dungeon_monster_drop_list, dungeon_monster_list, dungeon_list)

        # Create a mapping of skill IDs to monsters, for computing skillups
        skill_to_monster_list = defaultdict(list)
        for base_monster in base_monster_list:
            if base_monster.active_id:
                skill_to_monster_list[base_monster.active_id].append(base_monster.monster_id)

        self.full_monster_list = list()
        self.full_monster_map = {}
        for base_monster in base_monster_list:
            monster_id = base_monster.monster_id

            awakenings = sorted(monster_awoken_multimap[monster_id], key=lambda x: x.order)
            awakening_skills = [skill_map[x.awakening_id] for x in awakenings]
            additional_info = monster_add_info_map.get(monster_id)
            evos = monster_id_to_evo_multimap[monster_id]
            monster_info = monster_info_map[monster_id]
            active_skill = skill_map.get(base_monster.active_id)
            leader_skill = skill_map.get(base_monster.leader_id)
            leader_skill_data = skill_leader_data_map.get(base_monster.leader_id)
            drop_info_list = monster_id_to_drop_info_list.get(monster_id, [])
            series = series_map[monster_info.series_id]
            monster_price = monster_id_to_monster_price[monster_id]

            cur_evo = monster_to_current_evo_item.get(monster_id, None)
            mats_to_evo = monster_evo_to_mat_multimap[cur_evo.evo_id] if cur_evo else []
            used_for_evo = monster_mat_id_to_evod_monster_id_multimap[monster_id]

            monster_ids_with_skill = skill_to_monster_list.get(base_monster.active_id, list())

            full_monster = Monster(
                base_monster,
                monster_info,
                additional_info,
                awakening_skills,
                evos,
                active_skill,
                leader_skill,
                leader_skill_data,
                type_map,
                attribute_map,
                drop_info_list,
                series,
                monster_price,
                mats_to_evo,
                used_for_evo,
                monster_ids_with_skill,
                cur_evo)

            if na_only and not full_monster.on_na:
                continue

            addNickname(full_monster)
            addPrefixes(full_monster)

            self.full_monster_list.append(full_monster)
            self.full_monster_map[monster_id] = full_monster

        # For each monster, populate the list of monsters that they evo from
        for full_monster in self.full_monster_list:
            for evo_to_id in full_monster.evo_to:
                # Since na_only will be missing some 'to' monsters, safety first
                if evo_to_id in self.full_monster_map:
                    self.full_monster_map[evo_to_id].evo_from.append(full_monster.monster_id)

            mats_to_evo_monsters = list()
            for monster_id in full_monster.mats_to_evo:
                mats_to_evo_monsters.append(self.full_monster_map[monster_id])
            # Ugh. This is bad.
            # Really need to build an initial template monster, map it by ID, then
            # use that when building the individual monsters.
            full_monster.mats_to_evo = mats_to_evo_monsters

            used_for_evo_monsters = list()
            for monster_id in full_monster.used_for_evo:
                if monster_id in self.full_monster_map:
                    # Guard against na_only
                    used_for_evo_monsters.append(self.full_monster_map[monster_id])
            full_monster.used_for_evo = used_for_evo_monsters

        self.series_id_to_monsters = defaultdict(list)

        self.hp_monster_groups = list()
        self.lp_monster_groups = list()

        # Create monster groups
        for full_monster in self.full_monster_list:
            # Ignore monsters that can be evo'd to, they're not the base
            if len(full_monster.evo_from):
                full_monster.debug_info += ' | not root'
                continue

            # Populate pantheon mapping
            self.series_id_to_monsters[full_monster.series_id].append(full_monster)

            full_monster.debug_info += ' | root'
            # Recursively build the monster group
            mg = MonsterGroup()
            self.buildMonsterGroup(full_monster, mg)

            # Tag the group with the best nickname
            str_id = str(full_monster.monster_id_na)
            if str_id in group_overrides:
                mg.overrideNickname(group_overrides[str_id])
            else:
                mg.computeNickname()

            # Push the group size into each monster
            for m in mg.monsters:
                m.group_size = len(mg.monsters)
                m.debug_info += ' | grpsize ' + str(len(mg.monsters))
                m.alt_evos = [x for x in mg.monsters if x.monster_id != m.monster_id]

            # Compute tree farmable status
            farmable_evo = False
            pem_evo = False
            rem_evo = False
            mp_evo = False
            for m in mg.monsters:
                farmable_evo = farmable_evo or m.farmable
                pem_evo = pem_evo or m.in_pem
                rem_evo = rem_evo or m.in_rem
                mp_evo = mp_evo or m.in_mpshop

            # Override tree farmable status
            for m in mg.monsters:
                m.farmable_evo = farmable_evo
                m.pem_evo = pem_evo
                m.rem_evo = rem_evo
                m.mp_evo = mp_evo

            # Split monster groups into low or high priority ones
            if shouldFilterMonster(mg.monsters[0]) or shouldFilterGroup(mg):
                self.lp_monster_groups.append(mg)
            else:
                self.hp_monster_groups.append(mg)

        for full_monster in self.full_monster_list:
            for monster_id in full_monster.monster_ids_with_skill:
                if monster_id == '0':
                    continue

                skillup_monster = self.full_monster_map.get(monster_id)
                if not skillup_monster:
                    continue

                if not skillup_monster.rem_evo:
                    full_monster.monsters_with_skill.append(skillup_monster)

        # Unzip the monster groups into monster lists
        self.hp_monsters = list()
        self.lp_monsters = list()
        for mg in self.hp_monster_groups:
            for m in mg.monsters:
                self.hp_monsters.append(m)
                m.selection_priority = HIGH_SELECTION_PRIORITY
                m.debug_info += ' | HP'
        for mg in self.lp_monster_groups:
            for m in mg.monsters:
                self.lp_monsters.append(m)
                m.selection_priority = LOW_SELECTION_PRIORITY
                m.debug_info += ' | LP'

        # Sort the monster lists by largest group size first, then largest monster id
        def group_id_sort(m): return (m.group_size, m.monster_id_na)
        self.hp_monsters.sort(key=group_id_sort, reverse=True)
        self.lp_monsters.sort(key=group_id_sort, reverse=True)

        self.all_entries = {}
        self.two_word_entries = {}

        self.buildNicknameLists(self.hp_monsters)
        self.buildNicknameLists(self.lp_monsters)

        self.id_to_monster = {m.monster_id_na: m for m in self.full_monster_list}

        skill_rotation = padguide.loadJsonToItem('skillRotationList.jsp', padguide.PgSkillRotation)
        dated_skill_rotation = padguide.loadJsonToItem(
            'skillRotationListList.jsp', padguide.PgDatedSkillRotation)

        id_to_skill_rotation = {sr.tsr_seq: sr for sr in skill_rotation}
        merged_rotation = [padguide.PgMergedRotation(
            id_to_skill_rotation[dsr.tsr_seq], dsr) for dsr in dated_skill_rotation]

        skill_id_to_monsters = defaultdict(list)
        for m in self.full_monster_list:
            if m.active_skill:
                skill_id_to_monsters[m.active_skill.skill_id].append(m)

        monster_id_to_monster = {m.monster_id: m for m in self.full_monster_list}
        self.computeCurrentRotations(merged_rotation, 'US', NA_TZ_OBJ,
                                     monster_id_to_monster, skill_map, skill_id_to_monsters)
        self.computeCurrentRotations(merged_rotation, 'JP', JP_TZ_OBJ,
                                     monster_id_to_monster, skill_map, skill_id_to_monsters)

    def computeCurrentRotations(self, merged_rotation, server, server_tz, monster_id_to_monster, skill_map, skill_id_to_monsters):
        server_now = datetime.now().replace(tzinfo=server_tz).date()
        active_rotation = [mr for mr in merged_rotation if mr.server ==
                           server and mr.rotation_date <= server_now]
        server = normalizeServer(server)

        monsters_to_rotations = defaultdict(list)
        for ar in active_rotation:
            monsters_to_rotations[ar.monster_id].append(ar)

        cur_rotations = list()
        for _, rotations in monsters_to_rotations.items():
            cur_rotations.append(max(rotations, key=lambda x: x.rotation_date))

        for mr in cur_rotations:
            mr.resolved_monster = monster_id_to_monster[mr.monster_id]
            mr.resolved_active = skill_map[mr.active_id]

            mr.resolved_monster.server_actives[server] = mr.resolved_active
            monsters_with_skill = skill_id_to_monsters[mr.resolved_active.skill_id]
            for m in monsters_with_skill:
                if m.monster_id != mr.resolved_monster.monster_id:
                    m.server_skillups[server] = mr.resolved_monster

        return cur_rotations

    def maybeAdd(self, name_map, name, monster):
        if name not in name_map:
            name_map[name] = monster

    def buildNicknameLists(self, monster_list):
        for m in monster_list:
            self.maybeAdd(self.all_entries, m.nickname, m)
            for p in m.prefixes:
                self.maybeAdd(self.all_entries, p + m.nickname, m)
                self.maybeAdd(self.all_entries, p + ' ' + m.nickname, m)

            nickname_words = m.nickname.split(' ')
            if len(nickname_words) == 2:
                alt_nickname = nickname_words[1]
                self.maybeAdd(self.two_word_entries, alt_nickname, m)
                for p in m.prefixes:
                    n1 = p + alt_nickname
                    self.maybeAdd(self.two_word_entries, p + alt_nickname, m)
                    self.maybeAdd(self.two_word_entries, p + ' ' + alt_nickname, m)

            if m.roma_subname:
                self.maybeAdd(self.all_entries, m.roma_subname, m)

    def buildMonsterGroup(self, m: Monster, mg: MonsterGroup):
        mg.monsters.append(m)
        for mto_id in m.evo_to:
            if mto_id in self.full_monster_map:
                mto = self.full_monster_map[mto_id]
                self.buildMonsterGroup(mto, mg)

    def populateWithOverrides(self, nickname_text):
        nickname_reader = csv.reader(nickname_text.split('\n'), delimiter=',')
        for row in nickname_reader:
            if len(row) < 4:
                continue

            nickname = row[1].strip().lower()
            mId = row[2].strip()
            approved = row[3].strip().upper()

            if not (len(nickname) and len(mId) and len(approved)):
                continue

            if approved != 'TRUE' or not mId.isdigit():
                continue

            id = int(mId)
            if id in self.id_to_monster:
                self.all_entries[nickname] = self.id_to_monster[id]

    def computeMonsterDropInfoCombined(self,
                                       dungeon_monster_drop_list,  # unused
                                       dungeon_monster_list,
                                       dungeon_list):
        """Stuff for computing monster drops"""

        # TODO: consider merging in dungeon_monster_drop_list info
        dungeon_id_to_dungeon = {x.seq: x for x in dungeon_list}

        monster_id_to_drop_info = defaultdict(list)
        for dungeon_monster in dungeon_monster_list:
            monster_id = dungeon_monster.drop_monster_id
            dungeon_seq = dungeon_monster.dungeon_seq

            if dungeon_seq not in dungeon_id_to_dungeon:
                # In case downloaded files are out of sync, skip
                continue
            dungeon = dungeon_id_to_dungeon[dungeon_seq]

            info = padguide.PgMonsterDropInfoCombined(monster_id, None, dungeon_monster, dungeon)
            monster_id_to_drop_info[monster_id].append(info)

        return monster_id_to_drop_info


def shouldFilterMonster(m: Monster):
    lp_types = ['evolve', 'enhance', 'protected', 'awoken', 'vendor']
    lp_substrings = ['tamadra']
    lp_min_rarity = 2
    name = m.name_na.lower()

    failed_type = m.type1.lower() in lp_types
    failed_ss = any([x in name for x in lp_substrings])
    failed_rarity = m.rarity < lp_min_rarity
    failed_chibi = name == m.name_na

    return failed_type or failed_ss or failed_rarity or failed_chibi


def shouldFilterGroup(mg: MonsterGroup):
    lp_grp_min_rarity = 5
    max_rarity = max(m.rarity for m in mg.monsters)

    failed_max_rarity = max_rarity < lp_grp_min_rarity

    return failed_max_rarity


def createMultiplierText(hp1, atk1, rcv1, resist1, hp2, atk2, rcv2, resist2):
    def fmtNum(val):
        return ('{:.2f}').format(val).strip('0').rstrip('.')
    text = "{}/{}/{}".format(fmtNum(hp1 * hp2), fmtNum(atk1 * atk2), fmtNum(rcv1 * rcv2))
    if resist1 * resist2 < 1:
        resist1 = resist1 if resist1 < 1 else 0
        resist2 = resist2 if resist2 < 1 else 0
        text += ' Resist {}%'.format(fmtNum(100 * (1 - (1 - resist1) * (1 - resist2))))
    return text


def _map_awakenings_text(m: Monster):
    awakenings_row = ''
    unique_awakenings = set(m.awakening_names)
    for a in unique_awakenings:
        count = m.awakening_names.count(a)
        awakenings_row += ' {}x{}'.format(AWAKENING_NAME_MAP.get(a, a), count)
    awakenings_row = awakenings_row.strip()

    if not len(awakenings_row):
        awakenings_row = 'No Awakenings'

    return awakenings_row
