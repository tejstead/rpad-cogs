import asyncio
from builtins import filter, map
from collections import OrderedDict
from collections import defaultdict
import io
import json
import re
import traceback

from dateutil import tz
import discord
from discord.ext import commands
from enum import Enum
import prettytable

from __main__ import user_allowed, send_cmd_help

from . import padguide2
from . import rpadutils
from .rpadutils import *
from .rpadutils import CogSettings
from .utils import checks
from .utils.chat_formatting import *
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


INFO_PDX_TEMPLATE = 'http://www.puzzledragonx.com/en/monster.asp?n={}'
RPAD_PIC_TEMPLATE = 'https://f002.backblazeb2.com/file/miru-data/padimages/{}/full/{}.png'
RPAD_PORTRAIT_TEMPLATE = 'https://f002.backblazeb2.com/file/miru-data/padimages/{}/portrait/{}.png'
VIDEO_TEMPLATE = 'https://f002.backblazeb2.com/file/miru-data/padimages/animated/{}.mp4'
GIF_TEMPLATE = 'https://f002.backblazeb2.com/file/miru-data/padimages/animated/{}.gif'

YT_SEARCH_TEMPLATE = 'https://www.youtube.com/results?search_query={}'
SKYOZORA_TEMPLATE = 'http://pad.skyozora.com/pets/{}'


def get_pdx_url(m):
    return INFO_PDX_TEMPLATE.format(rpadutils.get_pdx_id(m))


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


class PadInfo:
    def __init__(self, bot):
        self.bot = bot

        self.settings = PadInfoSettings("padinfo")

        self.index_all = padguide2.empty_index()
        self.index_na = padguide2.empty_index()

        self.menu = Menu(bot)

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
        self.historic_lookups_file_path_id2 = "data/padinfo/historic_lookups_id2.json"
        if not dataIO.is_valid_json(self.historic_lookups_file_path):
            print("Creating empty historic_lookups.json...")
            dataIO.save_json(self.historic_lookups_file_path, {})

        if not dataIO.is_valid_json(self.historic_lookups_file_path_id2):
            print("Creating empty historic_lookups_id2.json...")
            dataIO.save_json(self.historic_lookups_file_path_id2, {})
        
        self.historic_lookups = dataIO.load_json(self.historic_lookups_file_path)
        self.historic_lookups_id2 = dataIO.load_json(self.historic_lookups_file_path_id2)

    def __unload(self):
        # Manually nulling out database because the GC for cogs seems to be pretty shitty
        self.index_all = padguide2.empty_index()
        self.index_na = padguide2.empty_index()
        self.historic_lookups = {}
        self.historic_lookups_id2 = {}

    async def reload_nicknames(self):
        await self.bot.wait_until_ready()
        while self == self.bot.get_cog('PadInfo'):
            try:
                await self.refresh_index()
                print('Done refreshing PadInfo')
            except Exception as ex:
                print("reload padinfo loop caught exception " + str(ex))
                traceback.print_exc()

            await asyncio.sleep(60 * 60 * 1)

    async def refresh_index(self):
        """Refresh the monster indexes."""
        pg_cog = self.bot.get_cog('PadGuide2')
        await pg_cog.wait_until_ready()
        self.index_all = pg_cog.create_index()
        self.index_na = pg_cog.create_index(lambda m: m.on_na)

    def get_monster_by_no(self, monster_no: int):
        pg_cog = self.bot.get_cog('PadGuide2')
        return pg_cog.get_monster_by_no(monster_no)

    @commands.command(pass_context=True)
    async def skillrotation(self, ctx, server: str='NA'):
        """Print the current rotating skillups for a server (NA/JP)"""
        server = normalizeServer(server)
        if server not in ['NA', 'JP']:
            await self.bot.say(inline('Supported servers are NA, JP'))
            return

        pg_cog = self.bot.get_cog('PadGuide2')
        monsters = pg_cog.database.rotating_skillups(server)

        for page in pagify(monsters_to_rotation_list(monsters, server, self.index_all)):
            await self.bot.say(box(page))

    @commands.command(pass_context=True)
    async def jpname(self, ctx, *, query: str):
        """Print the Japanese name of a monster"""
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            await self.bot.say(monsterToHeader(m))
            await self.bot.say(box(m.name_jp))
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(name="id", pass_context=True)
    async def _do_id_all(self, ctx, *, query: str):
        """Monster info (main tab)"""
        await self._do_id(ctx, query)

    @commands.command(name="idna", pass_context=True)
    async def _do_id_na(self, ctx, *, query: str):
        """Monster info (limited to NA monsters ONLY)"""
        await self._do_id(ctx, query, na_only=True)

    async def _do_id(self, ctx, query: str, na_only=False):
        m, err, debug_info = self.findMonster(query, na_only=na_only)
        if m is not None:
            await self._do_idmenu(ctx, m, self.id_emoji)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(name="id2", pass_context=True)
    async def _do_id2_all(self, ctx, *, query: str):
        """Monster info (main tab)"""
        await self._do_id2(ctx, query)
    
    @commands.command(name="id2na", pass_context=True)
    async def _do_id2_na(self, ctx, *, query: str):
        """Monster info (limited to NA monsters ONLY)"""
        await self._do_id2(ctx, query, na_only=True)

    async def _do_id2(self, ctx, query: str, na_only=False):
        m, err, debug_info = self.findMonster2(query, na_only=na_only)
        if m is not None:
            await self._do_idmenu(ctx, m, self.id_emoji)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(name="evos", pass_context=True)
    async def evos(self, ctx, *, query: str):
        """Monster info (evolutions tab)"""
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            await self._do_idmenu(ctx, m, self.evo_emoji)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(name="mats", pass_context=True, aliases=['evomats', 'evomat'])
    async def evomats(self, ctx, *, query: str):
        """Monster info (evo materials tab)"""
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            await self._do_idmenu(ctx, m, self.mats_emoji)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(pass_context=True)
    async def pantheon(self, ctx, *, query: str):
        """Monster info (pantheon tab)"""
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            menu = await self._do_idmenu(ctx, m, self.pantheon_emoji)
            if menu == EMBED_NOT_GENERATED:
                await self.bot.say(inline('Not a pantheon monster'))
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(pass_context=True)
    async def skillups(self, ctx, *, query: str):
        """Monster info (evolutions tab)"""
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            menu = await self._do_idmenu(ctx, m, self.skillups_emoji)
            if menu == EMBED_NOT_GENERATED:
                await self.bot.say(inline('No skillups available'))
        else:
            await self.bot.say(self.makeFailureMsg(err))

    async def _do_idmenu(self, ctx, m, starting_menu_emoji):
        id_embed = monsterToEmbed(m, self.get_emojis())
        evo_embed = monsterToEvoEmbed(m)
        mats_embed = monsterToEvoMatsEmbed(m)
        animated = self.check_monster_animated(m.monster_no_jp)
        pic_embed = monsterToPicEmbed(m, animated=animated)
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

    async def _do_evolistmenu(self, ctx, sm):
        monsters = sm.alt_evos
        monsters.sort(key=lambda m: m.monster_no)

        emoji_to_embed = OrderedDict()
        for idx, m in enumerate(monsters):
            emoji = char_to_emoji(str(idx))
            emoji_to_embed[emoji] = monsterToEmbed(m, self.get_emojis())
            if m == sm:
                starting_menu_emoji = emoji

        return await self._do_menu(ctx, starting_menu_emoji, emoji_to_embed, timeout=60)

    async def _do_menu(self, ctx, starting_menu_emoji, emoji_to_embed, timeout=30):
        if starting_menu_emoji not in emoji_to_embed:
            # Selected menu wasn't generated for this monster
            return EMBED_NOT_GENERATED

        remove_emoji = self.menu.emoji['no']
        emoji_to_embed[remove_emoji] = self.menu.reaction_delete_message

        try:
            result_msg, result_embed = await self.menu.custom_menu(ctx, emoji_to_embed, starting_menu_emoji, timeout=timeout)
            if result_msg and result_embed:
                # Message is finished but not deleted, clear the footer
                result_embed.set_footer(text=discord.Embed.Empty)
                await self.bot.edit_message(result_msg, embed=result_embed)
        except Exception as ex:
            print('Menu failure', ex)

    @commands.command(pass_context=True, aliases=['img'])
    async def pic(self, ctx, *, query: str):
        """Monster info (full image tab)"""
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            await self._do_idmenu(ctx, m, self.pic_emoji)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(pass_context=True, aliases=['stats'])
    async def otherinfo(self, ctx, *, query: str):
        """Monster info (misc info tab)"""
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            await self._do_idmenu(ctx, m, self.other_info_emoji)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(pass_context=True)
    async def lookup(self, ctx, *, query: str):
        """Short info results for a monster query"""
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            embed = monsterToHeaderEmbed(m)
            await self.bot.say(embed=embed)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(pass_context=True)
    async def evolist(self, ctx, *, query):
        """Monster info (for all monsters in the evo tree)"""
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            await self._do_evolistmenu(ctx, m)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(pass_context=True, aliases=['leaders', 'leaderskills', 'ls'])
    async def leaderskill(self, ctx, left_query: str, right_query: str=None, *, bad=None):
        """Display the multiplier and leaderskills for two monsters

        If either your left or right query contains spaces, wrap in quotes.
        e.g.: ^leaderskill "r sonia" "b sonia"
        """
        if bad:
            await self.bot.say(inline('Too many inputs. Try wrapping your queries in quotes.'))
            return

        # Handle a very specific failure case, user typing something like "uuvo ragdra"
        if ' ' not in left_query and right_query is not None and ' ' not in right_query and bad is None:
            combined_query = left_query + ' ' + right_query
            nm, err, debug_info = self._findMonster(combined_query)
            if nm and left_query in nm.prefixes:
                left_query = combined_query
                right_query = None

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
        """Whispers you info on how to craft monster queries for ^id"""
        await self.bot.whisper(box(HELP_MSG))

    @commands.command(pass_context=True)
    async def padsay(self, ctx, server, *, query: str=None):
        """Speak the voice line of a monster into your current chat"""
        voice = ctx.message.author.voice
        channel = voice.voice_channel
        if channel is None:
            await self.bot.say(inline('You must be in a voice channel to use this command'))
            return

        speech_cog = self.bot.get_cog('Speech')
        if not speech_cog:
            await self.bot.say(inline('Speech seems to be offline'))
            return

        if server.lower() not in ['na', 'jp']:
            query = server + ' ' + (query or '')
            server = 'na'
        query = query.strip().lower()

        m, err, debug_info = self.findMonster(query)
        if m is not None:
            base_dir = '/home/tactical0retreat/pad_data/voices/fixed'
            voice_file = os.path.join(base_dir, server, '{}.wav'.format(m.monster_no_na))
            header = '{} ({})'.format(monsterToHeader(m), server)
            if not os.path.exists(voice_file):
                await self.bot.say(inline('Could not find voice for ' + header))
                return
            await self.bot.say('Speaking for ' + header)
            await speech_cog.play_path(channel, voice_file)
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.group(pass_context=True)
    @checks.is_owner()
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
        msg = 'Lookup failed: {}.\n'.format(err)
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

    def findMonster2(self, query, na_only=False):
        query = rmdiacritics(query)
        nm, err, debug_info = self._findMonster2(query, na_only)
        
        monster_no = nm.monster_no if nm else -1
        self.historic_lookups_id2[query] = monster_no
        dataIO.save_json(self.historic_lookups_file_path_id2, self.historic_lookups_id2)
        
        m = self.get_monster_by_no(nm.monster_no) if nm else None
        
        return m, err, debug_info
    
    def _findMonster2(self, query, na_only=False):
        monster_index = self.index_na if na_only else self.index_all
        return monster_index.find_monster2(query)

    def map_awakenings_text(self, m):
        """Exported for use in other cogs"""
        return _map_awakenings_text(m)

    @padinfo.command(pass_context=True)
    @checks.is_owner()
    async def setanimationdir(self, ctx, *, animation_dir=''):
        """Set a directory containing animated images"""
        self.settings.setAnimationDir(animation_dir)
        await self.bot.say(inline('Done'))

    def check_monster_animated(self, monster_id: int):
        if not self.settings.animationDir():
            return False

        try:
            animated_ids = set()
            for f in os.listdir(self.settings.animationDir()):
                f = f.replace('.mp4', '')
                if f.isdigit() and int(f) == monster_id:
                    return True
        except:
            pass

        return False


def setup(bot):
    print('padinfo bot setup')
    n = PadInfo(bot)
    bot.add_cog(n)
    bot.loop.create_task(n.reload_nicknames())
    print('done adding padinfo bot')


class PadInfoSettings(CogSettings):
    def make_default_settings(self):
        config = {
            'animation_dir': '',
        }
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

    def animationDir(self):
        return self.bot_settings['animation_dir']

    def setAnimationDir(self, animation_dir):
        self.bot_settings['animation_dir'] = animation_dir
        self.save_settings()


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
    server_skillups = m.active_skill.server_skillups if m.active_skill else []

    if len(skillups_list) + len(server_skillups) == 0:
        return None

    embed = monsterToBaseEmbed(m)

    skillups_to_skip = []
    for server, skillup in server_skillups.items():
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


def monsterToPicEmbed(m: padguide2.PgMonster, animated=False):
    embed = monsterToBaseEmbed(m)
    url = monsterToPicUrl(m)
    embed.set_image(url=url)
    # Clear the thumbnail, don't need it on pic
    embed.set_thumbnail(url='')
    if animated:
        description = '[{}]({}) –– [{}]({})'.format(
            'HQ (MP4)', monsterToVideoUrl(m), 'LQ (GIF)', monsterToGifUrl(m))
        embed.add_field(name='Animated links', value=description)

    return embed


def monsterToVideoUrl(m: padguide2.PgMonster):
    return VIDEO_TEMPLATE.format(m.monster_no_jp)


def monsterToGifUrl(m: padguide2.PgMonster):
    return GIF_TEMPLATE.format(m.monster_no_jp)


def monsterToGifEmbed(m: padguide2.PgMonster):
    embed = monsterToBaseEmbed(m)
    url = monsterToGifUrl(m)
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

    if m.limitbreak_stats and m.limitbreak_stats > 1:
        def lb(x): return int(round(m.limitbreak_stats * x))
        stats_row_1 = 'Weighted {} | LB {}'.format(m.weighted_stats, lb(m.weighted_stats))
        stats_row_2 = '**HP** {} ({})\n**ATK** {} ({})\n**RCV** {} ({})'.format(
            m.hp, lb(m.hp), m.atk, lb(m.atk), m.rcv, lb(m.rcv))
    else:
        stats_row_1 = 'Weighted {}'.format(m.weighted_stats)
        stats_row_2 = '**HP** {}\n**ATK** {}\n**RCV** {}'.format(m.hp, m.atk, m.rcv)
    embed.add_field(name=stats_row_1, value=stats_row_2)

    awakenings_row = ''
    for idx, a in enumerate(m.awakenings):
        a = a.get_name()
        mapped_awakening = AWAKENING_NAME_MAP_RPAD.get(a, a)
        mapped_awakening = match_emoji(emoji_list, mapped_awakening)

        if mapped_awakening is None:
            mapped_awakening = AWAKENING_NAME_MAP.get(a, a)

        # Wrap superawakenings to the next line
        if len(m.awakenings) - idx == m.superawakening_count:
            awakenings_row += '\n{}'.format(mapped_awakening)
        else:
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
    skyozora_text = SKYOZORA_TEMPLATE.format(m.monster_no_jp)
    body_text += "\n**JP Name**: {} | [YouTube]({}) | [Skyozora]({})".format(
        m.name_jp, search_text, skyozora_text)

    if m.history_us:
        body_text += '\n**History:** {}'.format(m.history_us)

    body_text += '\n**Series:** {}'.format(m.series.name)
    body_text += '\n**Sell MP:** {:,}'.format(m.sell_mp)
    if m.buy_mp > 0:
        body_text += "  **Buy MP:** {:,}".format(m.buy_mp)

    if m.exp < 1000000:
        xp_text = '{:,}'.format(m.exp)
    else:
        xp_text = '{:.1f}'.format(m.exp / 1000000).rstrip('0').rstrip('.') + 'M'
    body_text += '\n**XP to Max:** {}'.format(xp_text)
    body_text += '  **Max Level:**: {}'.format(m.max_level)
    body_text += '\n**Rarity:** {} **Cost:** {}'.format(m.rarity, m.cost)

    if m.translated_jp_name:
        body_text += '\n**Google Translated:** {}'.format(m.translated_jp_name)

    embed.description = body_text

    return embed


def monsters_to_rotation_list(monster_list, server: str, index_all: padguide2.MonsterIndex):
    # Shorten some of the longer names
    name_remap = {
        'Extreme King Metal Tamadra': 'Fat Tama',
        'Extreme King Metal Dragon': 'EKMD',
        'Ancient Green Sacred Mask': 'Green Mask',
        'Ancient Blue Sacred Mask': 'Blue Mask',
    }
    ignore_monsters = [
        'Ancient Draggie Knight',
    ]

    monster_list.sort(key=lambda m: m.monster_no, reverse=True)
    next_rotation_date = None
    for m in monster_list:
        if server in m.future_skillup_rotation:
            next_rotation_date = m.future_skillup_rotation[server].rotation_date_str
            break

    cols = [server + ' Skillup', 'Current']
    if next_rotation_date:
        cols.append(next_rotation_date)
    tbl = prettytable.PrettyTable(cols)
    tbl.hrules = prettytable.HEADER
    tbl.vrules = prettytable.NONE
    tbl.align = "l"

    def cell_name(m: padguide2.PgMonster):
        nm = index_all.monster_no_to_named_monster[m.monster_no]
        name = nm.group_computed_basename.title()
        return name_remap.get(name, name)

    for m in monster_list:
        skill = m.server_actives[server]

        sm = skill.monsters_with_active
        # Since some newer monsters like jewel of creation are being used as
        # skillups, exclude them from the list of skillup targets.

        def is_bad_type(m):
            return set(['enhance', 'evolve', 'vendor']).intersection(set(m.types))
        sm = max(sm, key=lambda x: (not is_bad_type(x), x.monster_no))

        skillup_name = cell_name(m)
        if skillup_name in ignore_monsters:
            continue
        row = [skillup_name, cell_name(sm)]
        if next_rotation_date:
            if server in m.future_skillup_rotation:
                next_skill = m.future_skillup_rotation[server].skill
                nm = max(next_skill.monsters_with_active, key=lambda x: x.monster_no)
                row.append(cell_name(nm))
            else:
                row.append('')
        tbl.add_row(row)

    return tbl.get_string()


AWAKENING_NAME_MAP_RPAD = {
    'Enhanced Attack': 'boost_atk',
    'Enhanced HP': 'boost_hp',
    'Enhanced Heal': 'boost_rcv',

    'Enhanced Team HP': 'teamboost_hp',
    'Enhanced Team Attack': 'teamboost_atk',
    'Enhanced Team RCV': 'teamboost_rcv',

    'Reduced Attack': 'reduce_atk',
    'Reduced HP': 'reduce_hp',
    'Reduced RCV': 'reduce_rcv',

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
    'Super Enhanced Combo': 'misc_super_comboboost',
    'Guard Break': 'misc_guardbreak',
    'Multi Boost': 'misc_multiboost',
    'Additional Attack': 'misc_extraattack',
    'Skill Boost': 'misc_sb',
    'Extend Time': 'misc_te',
    'Two-Pronged Attack': 'misc_tpa',
    'Damage Void Shield Penetration': 'misc_voidshield',
    'Awoken Assist': 'misc_assist',

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

    'Skill Charge': 'misc_skillcharge',
    'Super Additional Attack': 'misc_super_extraattack',
    'Resistance-Bind＋': 'res_bind_super',
    'Extend Time＋': 'misc_te_super',
    'Resistance-Cloud': 'res_cloud',
    'Resistance-Board Restrict': 'res_seal',
    'Skill Boost＋': 'misc_sb_super',
    'L-Shape Attack': 'l_attack',
    'L-Shape Damage Reduction': 'l_shield',
    'Enhance when HP is below 50%': 'attack_boost_low',
    'Enhance when HP is above 80%': 'attack_boost_high',
    'Combo Orb': 'orb_combo',
    'Skill Voice': 'misc_voice',
    'Dungeon Bonus': 'misc_dungeonbonus',

    'Resistance-Dark＋': 'res_blind_super',
    'Resistance-Jammer＋': 'res_jammer_super',
    'Resistance-Poison＋': 'res_poison_super',
    'Jammer Orb’s Blessing': 'misc_jammerboost',
    'Poison Orb’s Blessing': 'misc_poisonboost',
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

    'Reduced HP': '-HP',
    'Reduced Attack': '-ATK',
    'Reduced RCV': '-RCV',

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
    'Awoken Assist': 'ASSIST',

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
