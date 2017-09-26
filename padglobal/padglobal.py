from collections import defaultdict
import csv
import difflib
import io
import os
import re

import discord
from discord.ext import commands

from __main__ import user_allowed, send_cmd_help

from .rpadutils import *
from .rpadutils import CogSettings
from .utils import checks
from .utils.dataIO import dataIO


PAD_CMD_HEADER = """
PAD Global Commands
^pad      : general command list
^padfaq   : FAQ command list
^boards   : optimal boards
^glossary : common PAD definitions
^which    : which monster evo info
"""

PADGLOBAL_COG = None

BLACKLISTED_CHARACTERS = '^[]*`~_'

PORTRAIT_TEMPLATE = 'https://storage.googleapis.com/mirubot/padimages/{}/portrait/{}.png'


def is_padglobal_admin_check(ctx):
    return PADGLOBAL_COG.settings.checkAdmin(ctx.message.author.id)


def is_padglobal_admin():
    return commands.check(is_padglobal_admin_check)


class PadGlobal:
    """Global PAD commands."""

    def __init__(self, bot):
        self.bot = bot
        self.file_path = "data/padglobal/commands.json"
        self.c_commands = dataIO.load_json(self.file_path)
        self.settings = PadGlobalSettings("padglobal")

        global PADGLOBAL_COG
        PADGLOBAL_COG = self

    @commands.command(pass_context=True)
    @is_padglobal_admin()
    async def debugiddump(self, ctx):
        padinfo_cog = self.bot.get_cog('PadInfo')
        mi = padinfo_cog.index_all

        async def write_send(nn_map, file_name):
            data_holder = io.StringIO()
            writer = csv.writer(data_holder)
            for nn, nm in nn_map.items():
                writer.writerow([nn, nm.monster_no_na, nm.name_na])
            bytes_data = io.BytesIO(data_holder.getvalue().encode())
            await self.bot.send_file(ctx.message.channel, bytes_data, filename=file_name)

        await write_send(mi.all_entries, 'all_entries.csv')
        await write_send(mi.two_word_entries, 'two_word_entries.csv')

    @commands.command(pass_context=True)
    @is_padglobal_admin()
    async def debugid(self, ctx, *, query):
        padinfo_cog = self.bot.get_cog('PadInfo')
        m, err, debug_info = padinfo_cog._findMonster(query)

        if m is None:
            await self.bot.say(box('No match: ' + err))
            return

        msg = "{}. {}".format(m.monster_no_na, m.name_na)
        msg += "\nLookup type: {}".format(debug_info)

        def list_or_none(l):
            if len(l) == 1:
                return '\n\t{}'.format(''.join(l))
            elif len(l):
                return '\n\t' + '\n\t'.join(sorted(l))
            else:
                return 'NONE'

        msg += "\n\nNickname original components:"
        msg += "\n monster_basename: {}".format(m.monster_basename)
        msg += "\n group_computed_basename: {}".format(m.group_computed_basename)
        msg += "\n extra_nicknames: {}".format(list_or_none(m.extra_nicknames))

        msg += "\n\nNickname final components:"
        msg += "\n basenames: {}".format(list_or_none(m.group_basenames))
        msg += "\n prefixes: {}".format(list_or_none(m.prefixes))

        msg += "\n\nAccepted nickname entries:"
        accepted_nn = list(filter(lambda nn: m.monster_no == padinfo_cog.index_all.all_entries[nn].monster_no,
                                  m.final_nicknames))
        accepted_twnn = list(filter(lambda nn: m.monster_no == padinfo_cog.index_all.two_word_entries[nn].monster_no,
                                    m.final_two_word_nicknames))

        msg += "\n nicknames: {}".format(list_or_none(accepted_nn))
        msg += "\n two_word_nicknames: {}".format(list_or_none(accepted_twnn))

        msg += "\n\nOverwritten nickname entries:"
        replaced_nn = list(filter(lambda nn: nn not in accepted_nn,
                                  m.final_nicknames))

        replaced_twnn = list(filter(lambda nn: nn not in accepted_twnn,
                                    m.final_two_word_nicknames))

        replaced_nn_info = map(lambda nn: (
            nn, padinfo_cog.index_all.all_entries[nn]), replaced_nn)
        replaced_twnn_info = map(
            lambda nn: (nn, padinfo_cog.index_all.two_word_entries[nn]), replaced_twnn)

        replaced_nn_text = list(map(lambda nn_info: '{} : {}. {}'.format(
            nn_info[0], nn_info[1].monster_no_na, nn_info[1].name_na),
            replaced_nn_info))

        replaced_twnn_text = list(map(lambda nn_info: '{} : {}. {}'.format(
            nn_info[0], nn_info[1].monster_no_na, nn_info[1].name_na),
            replaced_twnn_info))

        msg += "\n nicknames: {}".format(list_or_none(replaced_nn_text))
        msg += "\n two_word_nicknames: {}".format(list_or_none(replaced_twnn_text))

        msg += "\n\nNickname entry sort parts:"
        msg += "\n (is_low_priority, group_size, monster_no) : ({}, {}, {})".format(
            m.is_low_priority, m.group_size, m.monster_no)

        msg += "\n\nMatch selection sort parts:"
        msg += "\n (is_low_priority, rarity, monster_no_na) : ({}, {}, {})".format(
            m.is_low_priority, m.rarity, m.monster_no_na)

        for page in pagify(msg):
            await self.bot.say(box(page))

    @commands.command(pass_context=True)
    @is_padglobal_admin()
    async def forceindexreload(self, ctx):
        await self.bot.say('starting reload')
        padguide_cog = self.bot.get_cog('PadGuide2')
        await padguide_cog.reload_config_files()
        padinfo_cog = self.bot.get_cog('PadInfo')
        await padinfo_cog.refresh_index()
        await self.bot.say('finished reload')

    @commands.group(pass_context=True)
    @is_padglobal_admin()
    async def padglobal(self, context):
        """PAD global custom commands."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @padglobal.command(pass_context=True)
    async def add(self, ctx, command: str, *, text):
        """Adds a PAD global command

        Example:
        !padglobal add command_name Text you want
        """
        command = command.lower()
        text = clean_global_mentions(text)
        text = text.replace(u'\u200b', '')
        text = replace_emoji_names_with_code(self._get_emojis(), text)
        if command in self.bot.commands.keys():
            await self.bot.say("That is already a standard command.")
            return

        for c in BLACKLISTED_CHARACTERS:
            if c in command:
                await self.bot.say("Invalid character in name: {}".format(c))
                return

        if not self.c_commands:
            self.c_commands = {}

        op = 'EDITED' if command in self.c_commands else 'ADDED'
        self.c_commands[command] = text
        dataIO.save_json(self.file_path, self.c_commands)
        await self.bot.say("PAD command successfully {}.".format(op))

    @padglobal.command(pass_context=True)
    async def delete(self, ctx, command: str):
        """Deletes a PAD global command

        Example:
        !padglobal delete yourcommand"""
        command = command.lower()
        cmdlist = self.c_commands
        if command in cmdlist:
            cmdlist.pop(command, None)
            dataIO.save_json(self.file_path, self.c_commands)
            await self.bot.say("PAD command successfully deleted.")
        else:
            await self.bot.say("PAD command doesn't exist.")

    @padglobal.command(pass_context=True)
    async def setgeneral(self, ctx, command: str):
        """Sets a command to show up in ^pad (the default).

        Example:
        ^padglobal setgeneral yourcommand"""
        command = command.lower()
        if command not in self.c_commands:
            await self.bot.say("PAD command doesn't exist.")
            return

        self.settings.setGeneral(command)
        await self.bot.say("PAD command set to general.")

    @padglobal.command(pass_context=True)
    async def setfaq(self, ctx, command: str):
        """Sets a command to show up in ^padfaq.

        Example:
        ^padglobal setfaq yourcommand"""
        command = command.lower()
        if command not in self.c_commands:
            await self.bot.say("PAD command doesn't exist.")
            return

        self.settings.setFaq(command)
        await self.bot.say("PAD command set to faq.")

    @padglobal.command(pass_context=True)
    async def setboards(self, ctx, command: str):
        """Sets a command to show up in ^boards.

        Example:
        ^padglobal setboards yourcommand"""
        command = command.lower()
        if command not in self.c_commands:
            await self.bot.say("PAD command doesn't exist.")
            return

        self.settings.setBoards(command)
        await self.bot.say("PAD command set to boards.")

    @commands.command(pass_context=True)
    async def pad(self, ctx):
        """Shows PAD global command list"""
        configured = self.settings.faq() + self.settings.boards()
        cmdlist = {k: v for k, v in self.c_commands.items() if k not in configured}
        await self.print_cmdlist(ctx, cmdlist)

    @commands.command(pass_context=True)
    async def padfaq(self, ctx):
        """Shows PAD FAQ command list"""
        cmdlist = {k: v for k, v in self.c_commands.items() if k in self.settings.faq()}
        await self.print_cmdlist(ctx, cmdlist)

    @commands.command(pass_context=True)
    async def boards(self, ctx):
        """Shows PAD Boards command list"""
        cmdlist = {k: v for k, v in self.c_commands.items() if k in self.settings.boards()}
        await self.print_cmdlist(ctx, cmdlist)

    async def print_cmdlist(self, ctx, cmdlist, inline=False):
        if not cmdlist:
            await self.bot.say("There are no padglobal commands yet")
            return

        commands = list(cmdlist.keys())
        prefixes = defaultdict(int)

        for c in commands:
            m = re.match(r'^([a-zA-Z]+)\d+$', c)
            if m:
                grp = m.group(1)
                prefixes[grp] = prefixes[grp] + 1

        good_prefixes = [cmd for cmd, cnt in prefixes.items() if cnt > 1]
        prefix_to_suffix = defaultdict(list)
        prefix_to_other = defaultdict(list)

        i = 0
        msg = PAD_CMD_HEADER + "\n"

        if inline:
            for cmd in sorted([cmd for cmd in cmdlist.keys()]):
                msg += " {} : {}\n".format(cmd, cmdlist[cmd])
            for page in pagify(msg):
                await self.bot.whisper(box(page))
            return

        for cmd in sorted([cmd for cmd in cmdlist.keys()]):
            m = re.match(r'^([a-zA-Z]+)(\d+)$', cmd)
            if m:
                prefix = m.group(1)
                if prefix in good_prefixes:
                    suffix = m.group(2)
                    prefix_to_suffix[prefix].append(suffix)
                    continue

            should_skip = False
            for good_prefix in good_prefixes:
                if cmd.startswith(good_prefix):
                    prefix_to_other[prefix].append(cmd)
                    should_skip = True
                    break
            if should_skip:
                continue

            msg += " {}{}\n".format(ctx.prefix, cmd)

        if prefix_to_suffix:
            msg += "\nThe following commands are indexed:\n"
            for prefix in sorted(prefix_to_suffix.keys()):
                msg += " {}{}[n]:\n  ".format(ctx.prefix, prefix)

                for suffix in sorted(map(int, prefix_to_suffix[prefix])):
                    msg += " {}{}".format(prefix, suffix)

                if len(prefix_to_other[prefix]):
                    msg += "\n"
                    for cmd in sorted(prefix_to_other[prefix]):
                        msg += " {}{}".format(ctx.prefix, cmd)
                msg += "\n\n"

        for page in pagify(msg):
            await self.bot.whisper(box(page))

    @commands.command(pass_context=True)
    async def glossaryto(self, ctx, to_user: discord.Member, *, term: str):
        """Send a user a glossary entry

        ^glossaryto @tactical_retreat godfest
        """
        corrected_term, result = self.lookup_glossary(term)
        await self._do_send_term(ctx, to_user, term, corrected_term, result)

    @commands.command(pass_context=True)
    async def padto(self, ctx, to_user: discord.Member, *, term: str):
        """Send a user a pad/padfaq entry

        ^padto @tactical_retreat jewels?
        """
        corrected_term = self._lookup_command(term)
        result = self.c_commands.get(corrected_term, None)
        await self._do_send_term(ctx, to_user, term, corrected_term, result)

    async def _do_send_term(self, ctx, to_user: discord.Member, term, corrected_term, result):
        """Does the heavy lifting shared by padto and glossaryto."""
        if result:
            result_output = '**{}** : {}'.format(corrected_term, result)
            result = "{} asked me to send you this:\n{}".format(
                ctx.message.author.name, result_output)
            await self.bot.send_message(to_user, result)
            msg = "Sent that info to {}".format(to_user.name)
            if term != corrected_term:
                msg += ' (corrected to {})'.format(corrected_term)
            await self.bot.say(inline(msg))
        else:
            await self.bot.say(inline('No definition found'))

    @commands.command(pass_context=True)
    async def glossary(self, ctx, *, term: str=None):
        """Shows PAD Glossary entries"""
        if term:
            term, definition = self.lookup_glossary(term)
            if definition:
                definition_output = '**{}** : {}'.format(term, definition)
                await self.bot.say(definition_output)
            else:
                await self.bot.say(inline('No definition found'))
            return

        msg = self.glossary_to_text()
        for page in pagify(msg):
            await self.bot.whisper(page)

    def glossary_to_text(self):
        glossary = self.settings.glossary()
        msg = '__**PAD Glossary terms (also check out ^pad / ^padfaq / ^boards / ^which)**__'
        for term in sorted(glossary.keys()):
            definition = glossary[term]
            msg += '\n**{}** : {}'.format(term, definition)
        return msg

    def lookup_glossary(self, term):
        glossary = self.settings.glossary()
        term = term.lower()
        definition = glossary.get(term, None)

        if definition:
            return term, definition

        matches = self._get_corrected_cmds(term, glossary.keys())

        if not matches:
            matches = difflib.get_close_matches(term, glossary.keys(), n=1, cutoff=.8)

        if not matches:
            return term, None
        else:
            term = matches[0]
            return term, glossary[term]

    @padglobal.command(pass_context=True)
    async def addglossary(self, ctx, term, *, definition):
        """Adds a term to the glossary.
        If you want to use a multiple word term, enclose it in quotes.

        e.x. ^padglobal addglossary alb Awoken Liu Bei
        e.x. ^padglobal addglossary "never dathena" NA will never get dathena
        """
        term = term.lower()
        op = 'EDITED' if term in self.settings.glossary() else 'ADDED'
        self.settings.addGlossary(term, definition)
        await self.bot.say("PAD glossary term successfully {}.".format(op))

    @padglobal.command(pass_context=True)
    async def rmglossary(self, ctx, *, term):
        """Removes a term from the glossary."""
        self.settings.rmGlossary(term.lower())
        await self.bot.say("done")

    @commands.command(pass_context=True)
    async def which(self, ctx, *, term: str=None):
        """Shows PAD Which Monster entries"""
        if term:
            corrected_term, definition = self.lookup_which(term)
            if definition:
                if term != corrected_term:
                    await self.bot.say(inline('Corrected to: {}'.format(corrected_term)))
                await self.bot.say(definition)
            else:
                await self.bot.say(inline('No which info found'))
            return

        msg = self.which_to_text()
        for page in pagify(msg):
            await self.bot.whisper(page)

    def which_to_text(self):
        which = self.settings.which()
        msg = '__**PAD Which Monster (also check out ^pad / ^padfaq / ^boards / ^glossary)**__'
        msg += '```\n{}```'.format(', '.join(which))
        return msg

    def lookup_which(self, term):
        which = self.settings.which()
        term = term.lower().replace('?', '')
        definition = which.get(term, None)

        if definition:
            return term, definition

        matches = difflib.get_close_matches(term, which.keys(), n=1, cutoff=.8)

        if not matches:
            return term, None
        else:
            term = matches[0]
            return term, which[term]

    @padglobal.command(pass_context=True)
    async def addwhich(self, ctx, name, *, definition):
        """Adds an entry to the which monster evo list.
        If you want to use a multiple word name, enclose it in quotes.

        e.x. ^padglobal addwhich terra take the pixel one
        e.x. ^padglobal addwhich "trance terra" take the pixel one
        """
        name = name.lower()
        op = 'EDITED' if name in self.settings.which() else 'ADDED'
        self.settings.addWhich(name, definition)
        await self.bot.say("PAD which info successfully {}.".format(op))

    @padglobal.command(pass_context=True)
    async def rmwhich(self, ctx, *, name):
        """Removes an entry from the which monster evo list."""
        self.settings.rmWhich(name.lower())
        await self.bot.say("done")

    @padglobal.command(pass_context=True)
    @checks.is_owner()
    async def addadmin(self, ctx, user: discord.Member):
        """Adds a user to the pad global admin"""
        self.settings.addAdmin(user.id)
        await self.bot.say("done")

    @padglobal.command(pass_context=True)
    @checks.is_owner()
    async def rmadmin(self, ctx, user: discord.Member):
        """Removes a user from the pad global admin"""
        self.settings.rmAdmin(user.id)
        await self.bot.say("done")

    @padglobal.command(pass_context=True)
    @checks.is_owner()
    async def setemojiservers(self, ctx, *, emoji_servers=''):
        """Set the emoji servers by ID (csv)"""
        self.settings.emojiServers().clear()
        if emoji_servers:
            self.settings.setEmojiServers(emoji_servers.split(','))
        await self.bot.say(inline('Set {} servers'.format(len(self.settings.emojiServers()))))

    def _get_emojis(self):
        emojis = list()
        for server_id in self.settings.emojiServers():
            emojis.extend(self.bot.get_server(server_id).emojis)
        return emojis

    @padglobal.command(pass_context=True)
    async def addemoji(self, ctx, monster_id: int, server: str='jp'):
        """Create padglobal monster emoji by id..

        Uses jp monster IDs by default. You only need to change to na if you want to add
        voltron or something.

        If you add a jp ID, it will look like ':pad_123:'.
        If you add a na ID, it will look like ':pad_na_123:'.
        """
        all_emoji_servers = self.settings.emojiServers()
        if not all_emoji_servers:
            await self.bot.say('No emoji servers set')
            return

        if server not in ['na', 'jp']:
            await self.bot.say('Server must be one of [jp, na]')
            return

        if monster_id <= 0:
            await self.bot.say('Invalid monster id')
            return

        server_ids = self.settings.emojiServers()
        all_emojis = self._get_emojis()

        source_url = PORTRAIT_TEMPLATE.format(server, monster_id)
        emoji_name = 'pad_' + ('na_' if server == 'na' else '') + str(monster_id)

        for e in all_emojis:
            if emoji_name == e.name:
                await self.bot.say(inline('Already exists'))
                return

        for server_id in server_ids:
            emoji_server = self.bot.get_server(server_id)
            if len(emoji_server.emojis) < 50:
                break

        try:
            async with aiohttp.get(source_url) as resp:
                emoji_content = await resp.read()
                await self.bot.create_custom_emoji(emoji_server, name=emoji_name, image=emoji_content)
                await self.bot.say(inline('Done creating emoji named {}'.format(emoji_name)))
        except Exception as ex:
            await self.bot.say(box('Error:\n' + str(ex)))

    async def checkCC(self, message):
        if len(message.content) < 2:
            return

        prefix = self.get_prefix(message)

        if not prefix:
            return

        cmd = message.content[len(prefix):]
        final_cmd = self._lookup_command(cmd)
        if final_cmd is None:
            # Temporary redirect to ^which
            if cmd.startswith('which') and len(cmd) > len('which') and not cmd.startswith('which '):
                await self.bot.send_message(message.channel, inline('^which is now a dedicated command, try that instead'))
            return

        if final_cmd != cmd:
            await self.bot.send_message(message.channel, inline('Corrected to: {}'.format(final_cmd)))
        result = self.c_commands[final_cmd]

        cmd = self.format_cc(result, message)

        emoji_list = message.server.emojis if message.server else []
        await self.bot.send_message(message.channel, result)

    def _lookup_command(self, cmd):
        """Returns the corrected cmd name.

        Checks the raw command list, and if that fails, applies some corrections and takes
        the most likely result. Returns None if no good match.
        """
        cmdlist = self.c_commands.keys()
        if cmd in cmdlist:
            return cmd
        elif cmd.lower() in cmdlist:
            return cmd.lower()
        else:
            corrected_cmds = self._get_corrected_cmds(cmd, cmdlist)
            if corrected_cmds:
                return corrected_cmds[0]

        return None

    def _get_corrected_cmds(self, cmd, options):
        """Applies some corrections to cmd and returns the best matches in order."""
        cmd = cmd.lower()
        adjusted_cmd = [
            cmd + 's',
            cmd + '?',
            cmd + 's?',
            cmd.rstrip('?'),
            cmd.rstrip('s'),
            cmd.rstrip('s?'),
            cmd.rstrip('s?') + 's',
            cmd.rstrip('s?') + '?',
            cmd.rstrip('s?') + 's?',
        ]
        return [x for x in adjusted_cmd if x in options]

    def get_prefix(self, message):
        for p in self.bot.settings.get_prefixes(message.server):
            if message.content.startswith(p):
                return p
        return False

    def format_cc(self, command, message):
        results = re.findall("\{([^}]+)\}", command)
        for result in results:
            param = self.transform_parameter(result, message)
            command = command.replace("{" + result + "}", param)
        return command

    def transform_parameter(self, result, message):
        """
        For security reasons only specific objects are allowed
        Internals are ignored
        """
        raw_result = "{" + result + "}"
        objects = {
            "message": message,
            "author": message.author,
            "channel": message.channel,
            "server": message.server
        }
        if result in objects:
            return str(objects[result])
        try:
            first, second = result.split(".")
        except ValueError:
            return raw_result
        if first in objects and not second.startswith("_"):
            first = objects[first]
        else:
            return raw_result
        return str(getattr(first, second, raw_result))


def check_folders():
    if not os.path.exists("data/padglobal"):
        print("Creating data/padglobal folder...")
        os.makedirs("data/padglobal")


def check_files():
    f = "data/padglobal/commands.json"
    if not dataIO.is_valid_json(f):
        print("Creating empty commands.json...")
        dataIO.save_json(f, {})


def setup(bot):
    check_folders()
    check_files()
    n = PadGlobal(bot)
    bot.add_listener(n.checkCC, "on_message")
    bot.add_cog(n)


class PadGlobalSettings(CogSettings):
    def make_default_settings(self):
        config = {
            'admins': [],
            'faq': [],
            'boards': [],
            'glossary': {},
            'which': {},
        }
        return config

    def admins(self):
        return self.bot_settings['admins']

    def checkAdmin(self, user_id):
        admins = self.admins()
        return user_id in admins

    def addAdmin(self, user_id):
        admins = self.admins()
        if user_id not in admins:
            admins.append(user_id)
            self.save_settings()

    def rmAdmin(self, user_id):
        admins = self.admins()
        if user_id in admins:
            admins.remove(user_id)
            self.save_settings()

    def faq(self):
        key = 'faq'
        if key not in self.bot_settings:
            self.bot_settings[key] = []
        return self.bot_settings[key]

    def boards(self):
        key = 'boards'
        if key not in self.bot_settings:
            self.bot_settings[key] = {}
        return self.bot_settings[key]

    def clearCmd(self, cmd):
        if cmd in self.faq():
            self.faq().remove(cmd)
        if cmd in self.boards():
            self.boards().remove(cmd)

    def setGeneral(self, cmd):
        self.clearCmd(cmd)
        self.save_settings()

    def setFaq(self, cmd):
        self.clearCmd(cmd)
        self.faq().append(cmd)
        self.save_settings()

    def setBoards(self, cmd):
        self.clearCmd(cmd)
        self.boards().append(cmd)
        self.save_settings()

    def glossary(self):
        key = 'glossary'
        if key not in self.bot_settings:
            self.bot_settings[key] = {}
        return self.bot_settings[key]

    def addGlossary(self, term, definition):
        self.glossary()[term] = definition
        self.save_settings()

    def rmGlossary(self, term):
        glossary = self.glossary()
        if term in glossary:
            glossary.pop(term)
            self.save_settings()

    def which(self):
        key = 'which'
        if key not in self.bot_settings:
            self.bot_settings[key] = {}
        return self.bot_settings[key]

    def addWhich(self, name, text):
        self.which()[name] = text
        self.save_settings()

    def rmWhich(self, name):
        which = self.which()
        if name in which:
            which.pop(name)
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
