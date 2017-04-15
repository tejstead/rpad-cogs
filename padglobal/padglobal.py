from collections import defaultdict
import difflib
import os
import re

import discord
from discord.ext import commands

from __main__ import user_allowed, send_cmd_help

from .rpadutils import *
from .utils import checks
from .utils.cog_settings import *
from .utils.dataIO import dataIO


PAD_CMD_HEADER = """
PAD Global Commands
^pad      : general command list
^padfaq   : FAQ command list
^boards   : optimal boards
^glossary : common PAD definitions
"""

PADGLOBAL_COG = None

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

    @commands.group(pass_context=True)
    @is_padglobal_admin()
    async def padglobal(self, context):
        """PAD global custom commands."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @padglobal.command(pass_context=True)
    async def add(self, ctx, command : str, *, text):
        """Adds a PAD global command

        Example:
        !padglobal add command_name Text you want
        """
        command = command.lower()
        if command in self.bot.commands.keys():
            await self.bot.say("That is already a standard command.")
            return
        if not self.c_commands:
            self.c_commands = {}
        cmdlist = self.c_commands
        cmdlist[command] = text
        dataIO.save_json(self.file_path, self.c_commands)
        await self.bot.say("PAD command successfully added/edited.")

    @padglobal.command(pass_context=True)
    async def delete(self, ctx, command : str):
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
    async def setgeneral(self, ctx, command : str):
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
    async def setfaq(self, ctx, command : str):
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
    async def setboards(self, ctx, command : str):
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
        cmdlist = {k:v for k, v in self.c_commands.items() if k not in configured}
        await self.print_cmdlist(ctx, cmdlist)

    @commands.command(pass_context=True)
    async def padfaq(self, ctx):
        """Shows PAD FAQ command list"""
        cmdlist = {k:v for k, v in self.c_commands.items() if k in self.settings.faq()}
        await self.print_cmdlist(ctx, cmdlist)

    @commands.command(pass_context=True)
    async def boards(self, ctx):
        """Shows PAD Boards command list"""
        cmdlist = {k:v for k, v in self.c_commands.items() if k in self.settings.boards()}
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
                    break;
            if should_skip: continue

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
    async def glossaryto(self, ctx, to_user : discord.Member, *, term : str):
        """Send a user a glossary or pad/padfaq entry

        ^glossaryto @tactical_retreat jewels?
        """
        corrected_term = term
        cmd_items = {k:v for k, v in self.c_commands.items()}
        result = None
        if term in cmd_items:
            result = cmd_items[term]
        else:
            corrected_term, result = self.lookup_glossary(term)

        if result:
            result_output = '**{}** : {}'.format(corrected_term, result)
            result = "{} asked me to send you this:\n{}".format(ctx.message.author.name, result_output)
            await self.bot.send_message(to_user, result)
            msg = "Sent that info to {}".format(to_user.name)
            if term != corrected_term:
                msg += ' (corrected to {})'.format(corrected_term)
            await self.bot.say(inline(msg))
        else:
            await self.bot.say(inline('No definition found'))

    @commands.command(pass_context=True)
    async def glossary(self, ctx, *, term : str=None):
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
        msg = '__**PAD Glossary terms (also check out ^pad / ^padfaq / ^boards)**__'
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

        matches = difflib.get_close_matches(term, glossary.keys(), n=1)
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
        self.settings.addGlossary(term.lower(), definition)
        await self.bot.say("done")

    @padglobal.command(pass_context=True)
    async def rmglossary(self, ctx, *, term):
        """Removes a term from the glossary."""
        self.settings.rmGlossary(term.lower())
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

    async def checkCC(self, message):
        if len(message.content) < 2:
            return

        prefix = self.get_prefix(message)

        if not prefix:
            return

        cmdlist = self.c_commands
        cmd = message.content[len(prefix):]
        if cmd in cmdlist.keys():
            cmd = cmdlist[cmd]
            cmd = self.format_cc(cmd, message)
            await self.bot.send_message(message.channel, cmd)
        elif cmd.lower() in cmdlist.keys():
            cmd = cmdlist[cmd.lower()]
            cmd = self.format_cc(cmd, message)
            await self.bot.send_message(message.channel, cmd)

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
            "message" : message,
            "author"  : message.author,
            "channel" : message.channel,
            "server"  : message.server
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
          'admins' : [],
          'faq' : [],
          'boards' : [],
          'glossary' : {},
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
        if cmd in self.faq(): self.faq().remove(cmd)
        if cmd in self.boards(): self.boards().remove(cmd)

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
