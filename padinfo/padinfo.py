import asyncio
from builtins import filter, map
from collections import OrderedDict, Counter
from collections import defaultdict
import csv
from datetime import datetime
from datetime import timedelta
import difflib
from enum import Enum
import http.client
import io
from itertools import groupby
import json
from operator import itemgetter
import os
import re
import sys
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

from . import padguide2
from .rpadutils import *
from .utils import checks
from .utils.chat_formatting import *
from .utils.cog_settings import *
from .utils.dataIO import dataIO


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


INFO_PDX_TEMPLATE = 'http://www.puzzledragonx.com/en/monster.asp?n={}'
RPAD_PIC_TEMPLATE = 'https://storage.googleapis.com/mirubot/padimages/{}/full/{}.png'
RPAD_PORTRAIT_TEMPLATE = 'https://storage.googleapis.com/mirubot/padimages/{}/portrait/{}.png'

YT_SEARCH_TEMPLATE = 'https://www.youtube.com/results?search_query={}'

# This was overwritten by voltron. PDX opted to copy it +10,000 ids away
CROWS_1 = {x: x + 10000 for x in range(2601, 2635 + 1)}
# This isn't overwritten but PDX adjusted anyway
CROWS_2 = {x: x + 10000 for x in range(3460, 3481 + 1)}

PDX_JP_ADJUSTMENTS = {}
PDX_JP_ADJUSTMENTS.update(CROWS_1)
PDX_JP_ADJUSTMENTS.update(CROWS_2)


def get_pdx_url(m):
    pdx_id = m.monster_no_na
    if int(m.monster_no) == m.monster_no_jp:
        pdx_id = PDX_JP_ADJUSTMENTS.get(pdx_id, pdx_id)
    return INFO_PDX_TEMPLATE.format(pdx_id)


def get_portrait_url(m):
    if int(m.monster_no) != m.monster_no_na:
        return RPAD_PORTRAIT_TEMPLATE.format('na', m.monster_no_na)
    else:
        return RPAD_PORTRAIT_TEMPLATE.format('jp', m.monster_no_jp)


def get_pic_url(m):
    if int(m.monster_no) != m.monster_no_na:
        return RPAD_PIC_TEMPLATE.format('na', m.monster_no_na)
    else:
        return RPAD_PIC_TEMPLATE.format('jp', m.monster_no_jp)


EXPOSED_PAD_INFO = None


class PadInfo:
    def __init__(self, bot):
        self.bot = bot

        self.settings = PadInfoSettings("padinfo")

        self.index_all = padguide2.empty_index()
        self.index_na = padguide2.empty_index()

        self.menu = Menu(bot)

        global EXPOSED_PAD_INFO
        EXPOSED_PAD_INFO = self

        # These emojis are the keys into the idmenu submenus
        self.id_emoji = '\N{INFORMATION SOURCE}'
        self.evo_emoji = char_to_emoji('e')
        self.mats_emoji = char_to_emoji('m')
        self.ls_emoji = '\N{INFORMATION SOURCE}'
        self.left_emoji = char_to_emoji('l')
        self.right_emoji = char_to_emoji('r')
        self.pantheon_emoji = '\N{CLASSICAL BUILDING}'
        self.skillups_emoji = '\N{MEAT ON BONE}'
        self.pic_emoji = '\N{FRAME WITH PICTURE}'
        self.other_info_emoji = '\N{SCROLL}'

        self.historic_lookups_file_path = "data/padinfo/historic_lookups.json"
        if not dataIO.is_valid_json(self.historic_lookups_file_path):
            print("Creating empty historic_lookups.json...")
            dataIO.save_json(self.historic_lookups_file_path, {})

        self.historic_lookups = dataIO.load_json(self.historic_lookups_file_path)

    async def reload_nicknames(self):
        await self.bot.wait_until_ready()
        while self == self.bot.get_cog('PadInfo'):
            try:
                self.refresh_index()
            except Exception as ex:
                print("reload padinfo loop caught exception " + str(ex))
                traceback.print_exc()

            await asyncio.sleep(60 * 60 * 1)

    def refresh_index(self):
        """Refresh the monster indexes."""
        pg_cog = self.bot.get_cog('PadGuide2')
        self.index_all = pg_cog.create_index()
        self.index_na = pg_cog.create_index(lambda m: m.on_na)

    def get_monster_by_no(self, monster_no: int):
        pg_cog = self.bot.get_cog('PadGuide2')
        return pg_cog.get_monster_by_no(monster_no)

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
        other_info_embed = monsterToOtherInfoEmbed(m)

        emoji_to_embed = OrderedDict()
        emoji_to_embed[self.id_emoji] = id_embed
        emoji_to_embed[self.evo_emoji] = evo_embed
        emoji_to_embed[self.mats_emoji] = mats_embed
        emoji_to_embed[self.pic_emoji] = pic_embed

        pantheon_embed = monsterToPantheonEmbed(m)
        if pantheon_embed:
            emoji_to_embed[self.pantheon_emoji] = pantheon_embed

        skillups_embed = monsterToSkillupsEmbed(m)
        if skillups_embed:
            emoji_to_embed[self.skillups_emoji] = skillups_embed

        emoji_to_embed[self.other_info_emoji] = other_info_embed

        return await self._do_menu(ctx, starting_menu_emoji, emoji_to_embed)

    async def _do_menu(self, ctx, starting_menu_emoji, emoji_to_embed):
        if starting_menu_emoji not in emoji_to_embed:
            # Selected menu wasn't generated for this monster
            return EMBED_NOT_GENERATED

        remove_emoji = self.menu.emoji['no']
        emoji_to_embed[remove_emoji] = self.menu.reaction_delete_message

        try:
            result_msg, result_embed = await self.menu.custom_menu(ctx, emoji_to_embed, starting_menu_emoji, timeout=30)
            if result_msg and result_embed:
                # Message is finished but not deleted, clear the footer
                result_embed.set_footer(text=discord.Embed.Empty)
                await self.bot.edit_message(result_msg, embed=result_embed)
        except Exception as ex:
            print('Menu failure', ex)

    @commands.command(pass_context=True, aliases=['img'])
    async def pic(self, ctx, *, query):
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            await self._do_idmenu(ctx, m, self.pic_emoji)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(pass_context=True)
    async def lookup(self, ctx, *, query):
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            embed = monsterToHeaderEmbed(m)
            await self.bot.say(embed=embed)
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

        emoji_to_embed = OrderedDict()
        emoji_to_embed[self.ls_emoji] = monstersToLsEmbed(left_m, right_m)
        emoji_to_embed[self.left_emoji] = monsterToEmbed(left_m, self.get_emojis())
        emoji_to_embed[self.right_emoji] = monsterToEmbed(right_m, self.get_emojis())

        await self._do_menu(ctx, self.ls_emoji, emoji_to_embed)

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
        nm, err, debug_info = self._findMonster(query, na_only)

        monster_no = nm.monster_no if nm else -1
        self.historic_lookups[query] = monster_no
        dataIO.save_json(self.historic_lookups_file_path, self.historic_lookups)

        m = self.get_monster_by_no(nm.monster_no) if nm else None

        return m, err, debug_info

    def _findMonster(self, query, na_only=False):
        monster_index = self.index_na if na_only else self.index_all
        return monster_index.find_monster(query)

    def map_awakenings_text(self, m):
        """Exported for use in other cogs"""
        return _map_awakenings_text(m)


def setup(bot):
    print('padinfo bot setup')
    n = PadInfo(bot)
    bot.add_cog(n)
    bot.loop.create_task(n.reload_nicknames())
    print('done adding padinfo bot')


class PadInfoSettings(CogSettings):
    def make_default_settings(self):
        config = {}
        return config

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


def monsterToInfoText(m: padguide2.PgMonster):
    header = monsterToHeader(m)

    if m.roma_subname:
        header += ' [{}]'.format(m.roma_subname)

    if not m.on_na:
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


def monsterToHeader(m: padguide2.PgMonster, link=False):
    msg = 'No. {} {}'.format(m.monster_no_na, m.name_na)
    return '[{}]({})'.format(msg, get_pdx_url(m)) if link else msg


def monsterToJpSuffix(m: padguide2.PgMonster):
    suffix = ""
    if m.roma_subname:
        suffix += ' [{}]'.format(m.roma_subname)
    if not m.on_na:
        suffix += ' (JP only)'
    return suffix


def monsterToLongHeader(m: padguide2.PgMonster, link=False):
    msg = monsterToHeader(m) + monsterToJpSuffix(m)
    return '[{}]({})'.format(msg, get_pdx_url(m)) if link else msg


def monsterToLongHeaderWithAttr(m: padguide2.PgMonster, link=False):
    header = 'No. {} {} {}'.format(
        m.monster_no_na,
        "({}{})".format(attr_prefix_map[m.attr1], "/" +
                        attr_prefix_map[m.attr2] if m.attr2 else ""),
        m.name_na)
    msg = header + monsterToJpSuffix(m)
    return '[{}]({})'.format(msg, get_pdx_url(m)) if link else msg


def monsterToEvoText(m: padguide2.PgMonster):
    output = monsterToLongHeader(m)
    for ae in sorted(m.alt_evos, key=lambda x: int(x.monster_no)):
        output += "\n\t- {}".format(monsterToLongHeader(ae))
    return output


def monsterToThumbnailUrl(m: padguide2.PgMonster):
    return get_portrait_url(m)


def monsterToBaseEmbed(m: padguide2.PgMonster):
    header = monsterToLongHeader(m)
    embed = discord.Embed()
    embed.set_thumbnail(url=monsterToThumbnailUrl(m))
    embed.title = header
    embed.url = get_pdx_url(m)
    embed.set_footer(text='Requester may click the reactions below to switch tabs')
    return embed


def monsterToEvoEmbed(m: padguide2.PgMonster):
    embed = monsterToBaseEmbed(m)

    if not len(m.alt_evos):
        embed.description = 'No alternate evos'
        return embed

    field_name = '{} alternate evos'.format(len(m.alt_evos))
    field_data = ''
    for ae in sorted(m.alt_evos, key=lambda x: int(x.monster_no)):
        field_data += "{}\n".format(monsterToLongHeader(ae, link=True))

    embed.add_field(name=field_name, value=field_data)

    return embed


def monsterToEvoMatsEmbed(m: padguide2.PgMonster):
    embed = monsterToBaseEmbed(m)

    mats_for_evo_size = len(m.mats_for_evo)
    material_of_size = len(m.material_of)

    field_name = 'Evo materials'
    field_data = ''
    if mats_for_evo_size:
        for ae in m.mats_for_evo:
            field_data += "{}\n".format(monsterToLongHeader(ae, link=True))
    else:
        field_data = 'None'
    embed.add_field(name=field_name, value=field_data)

    if not material_of_size:
        return embed

    field_name = 'Material for'
    field_data = ''
    if material_of_size > 5:
        field_data = '{} monsters'.format(material_of_size)
    else:
        item_count = min(material_of_size, 5)
        for ae in sorted(m.material_of, key=lambda x: x.monster_no_na, reverse=True)[:item_count]:
            field_data += "{}\n".format(monsterToLongHeader(ae, link=True))
    embed.add_field(name=field_name, value=field_data)

    return embed


def monsterToPantheonEmbed(m: padguide2.PgMonster):
    full_pantheon = m.series.monsters
    pantheon_list = list(filter(lambda x: x.evo_from is None, full_pantheon))
    if len(pantheon_list) == 0 or len(pantheon_list) > 6:
        return None

    embed = monsterToBaseEmbed(m)

    field_name = 'Pantheon: ' + m.series.name
    field_data = ''
    for monster in sorted(pantheon_list, key=lambda x: x.monster_no_na):
        field_data += '\n' + monsterToHeader(monster, link=True)
    embed.add_field(name=field_name, value=field_data)

    return embed


def monsterToSkillupsEmbed(m: padguide2.PgMonster):
    skillups_list = m.active_skill.monsters_with_active if m.active_skill else []
    skillups_list = list(filter(lambda m: m.sell_mp < 3000, skillups_list))
    if len(skillups_list) + len(m.server_actives) == 0:
        return None

    embed = monsterToBaseEmbed(m)

    skillups_to_skip = list()
    for server, skillup in m.server_skillups.items():
        skillup_header = 'Skillup in ' + server
        skillup_body = monsterToHeader(skillup, link=True)
        embed.add_field(name=skillup_header, value=skillup_body)
        skillups_to_skip.append(skillup.monster_no_na)

    field_name = 'Skillups'
    field_data = ''

    # Prevent huge skillup lists
    if len(skillups_list) > 8:
        field_data = '({} skillups omitted)'.format(len(skillups_list) - 8)
        skillups_list = skillups_list[0:8]

    for monster in sorted(skillups_list, key=lambda x: x.monster_no_na):
        if monster.monster_no_na in skillups_to_skip:
            continue
        field_data += '\n' + monsterToHeader(monster, link=True)

    if len(field_data.strip()):
        embed.add_field(name=field_name, value=field_data)

    return embed


def monsterToPicUrl(m: padguide2.PgMonster):
    return get_pic_url(m)


def monsterToPicEmbed(m: padguide2.PgMonster):
    embed = monsterToBaseEmbed(m)
    url = monsterToPicUrl(m)
    embed.set_image(url=url)
    # Clear the thumbnail, don't need it on pic
    embed.set_thumbnail(url='')
    return embed


def monstersToLsEmbed(left_m: padguide2.PgMonster, right_m: padguide2.PgMonster):
    lhp, latk, lrcv, lresist = left_m.leader_skill_data.get_data()
    rhp, ratk, rrcv, rresist = right_m.leader_skill_data.get_data()
    multiplier_text = createMultiplierText(lhp, latk, lrcv, lresist, rhp, ratk, rrcv, rresist)

    embed = discord.Embed()
    embed.title = 'Multiplier [{}]\n\n'.format(multiplier_text)
    description = ''
    description += '\n**{}**\n{}'.format(
        monsterToHeader(left_m, link=True),
        left_m.leader_skill.desc if left_m.leader_skill else 'None/Missing')
    description += '\n**{}**\n{}'.format(
        monsterToHeader(right_m, link=True),
        right_m.leader_skill.desc if right_m.leader_skill else 'None/Missing')
    embed.description = description

    return embed


def monsterToHeaderEmbed(m: padguide2.PgMonster):
    header = monsterToLongHeader(m, link=True)
    embed = discord.Embed()
    embed.description = header
    return embed


def monsterToTypeString(m: padguide2.PgMonster):
    output = m.type1
    if m.type2:
        output += '/' + m.type2
    if m.type3:
        output += '/' + m.type3
    return output


def monsterToAcquireString(m: padguide2.PgMonster):
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


def monsterToEmbed(m: padguide2.PgMonster, emoji_list):
    embed = monsterToBaseEmbed(m)

    info_row_1 = monsterToTypeString(m)
    acquire_text = monsterToAcquireString(m)

    info_row_2 = '**Rarity** {}\n**Cost** {}'.format(m.rarity, m.cost)
    if acquire_text:
        info_row_2 += '\n**{}**'.format(acquire_text)
    if m.is_inheritable:
        info_row_2 += '\n**Inheritable**'
    else:
        info_row_2 += '\n**Not inheritable**'

    embed.add_field(name=info_row_1, value=info_row_2)

    stats_row_1 = 'Weighted {}'.format(m.weighted_stats)
    stats_row_2 = '**HP** {}\n**ATK** {}\n**RCV** {}'.format(m.hp, m.atk, m.rcv)
    embed.add_field(name=stats_row_1, value=stats_row_2)

    awakenings_row = ''
    for a in m.awakenings:
        a = a.get_name()
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

    # TODO: enable this later
#     if len(m.server_actives) >= 2:
    if False:
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

    ls_row = m.leader_skill.desc if m.leader_skill else 'None/Missing'
    ls_header = 'Leader Skill'
    if m.leader_skill_data:
        hp, atk, rcv, resist = m.leader_skill_data.get_data()
        multiplier_text = createMultiplierText(hp, atk, rcv, resist)
        ls_header += " [ {} ]".format(multiplier_text)
    embed.add_field(name=ls_header, value=ls_row, inline=False)

    return embed


def monsterToOtherInfoEmbed(m: padguide2.PgMonster):
    embed = monsterToBaseEmbed(m)
    # Clear the thumbnail, takes up too much space
    embed.set_thumbnail(url='')

    stat_cols = ['', 'Max', 'M297', 'Inh', 'I297']
    tbl = prettytable.PrettyTable(stat_cols)
    tbl.hrules = prettytable.NONE
    tbl.vrules = prettytable.NONE
    tbl.align = "r"
    hhp = m.hp + 99 * 10
    hatk = m.atk + 99 * 5
    hrcv = m.rcv + 99 * 3
    tbl.add_row(['HP', m.hp, hhp, int(m.hp * .1), int(hhp * .1)])
    tbl.add_row(['ATK', m.atk, hatk, int(m.atk * .05), int(hatk * .05)])
    tbl.add_row(['RCV', m.rcv, hrcv, int(m.rcv * .15), int(hrcv * .15)])

    body_text = box(tbl.get_string())

    search_text = YT_SEARCH_TEMPLATE.format(m.name_jp)
    body_text += "\nJP Name: [{}]({})".format(m.name_jp, search_text)

    if m.history_us:
        body_text += '\nHistory: {}'.format(m.history_us)

    body_text += '\nSeries: {}'.format(m.series.name)
    body_text += '\nSell MP: {:,}'.format(m.sell_mp)
    if m.buy_mp > 0:
        body_text += "  Buy MP: {:,}".format(m.buy_mp)

    if m.exp < 1000000:
        xp_text = '{:,}'.format(m.exp)
    else:
        xp_text = '{:.1f}'.format(m.exp / 1000000).rstrip('0').rstrip('.') + 'M'
    body_text += '\nXP to Max: {}'.format(xp_text)
    body_text += '  Max Level: {}'.format(m.max_level)

    embed.description = body_text

    return embed


AWAKENING_NAME_MAP_RPAD = {
    'Enhanced Attack': 'boost_atk',
    'Enhanced HP': 'boost_hp',
    'Enhanced Heal': 'boost_rcv',

    'Enhanced Team HP': 'teamboost_hp',
    'Enhanced Team Attack': 'teamboost_atk',
    'Enhanced Team RCV': 'teamboost_rcv',

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
    'Damage Void Shield Penetration': 'misc_voidshield',

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

    'Enhanced Team HP': 'TEAM-HP',
    'Enhanced Team Attack': 'TEAM-ATK',
    'Enhanced Team RCV': 'TEAM-RCV',

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
    'Damage Void Shield Penetration': 'VOID-BREAK',

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


def createMultiplierText(hp1, atk1, rcv1, resist1, hp2=None, atk2=None, rcv2=None, resist2=None):
    hp2, atk2, rcv2, resist2 = hp2 or hp1, atk2 or atk1, rcv2 or rcv1, resist2 or resist1

    def fmtNum(val):
        return ('{:.2f}').format(val).strip('0').rstrip('.')
    text = "{}/{}/{}".format(fmtNum(hp1 * hp2), fmtNum(atk1 * atk2), fmtNum(rcv1 * rcv2))
    if resist1 * resist2 < 1:
        resist1 = resist1 if resist1 < 1 else 0
        resist2 = resist2 if resist2 < 1 else 0
        text += ' Resist {}%'.format(fmtNum(100 * (1 - (1 - resist1) * (1 - resist2))))
    return text


def _map_awakenings_text(m: padguide2.PgMonster):
    awakenings_row = ''
    unique_awakenings = set(m.awakening_names)
    for a in unique_awakenings:
        count = m.awakening_names.count(a)
        awakenings_row += ' {}x{}'.format(AWAKENING_NAME_MAP.get(a, a), count)
    awakenings_row = awakenings_row.strip()

    if not len(awakenings_row):
        awakenings_row = 'No Awakenings'

    return awakenings_row


# TODO: move to padguide2
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
