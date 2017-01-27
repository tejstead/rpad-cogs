from collections import defaultdict
import os
import re

import discord
from discord.ext import commands

from __main__ import user_allowed, send_cmd_help

from .rpadutils import *
from .utils import checks
from .utils.cog_settings import *
from .utils.dataIO import dataIO


class PadGlobal:
    """Global PAD commands."""

    def __init__(self, bot):
        self.bot = bot
        self.file_path = "data/padglobal/commands.json"
        self.c_commands = dataIO.load_json(self.file_path)
        self.settings = PadGlobalSettings("padglobal")

    @commands.group(pass_context=True)
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
        if not self.settings.checkAdmin(ctx.message.author.id):
            await self.bot.say(inline("Not authorized to edit pad global commands"))
            return

        command = command.lower()
        if command in self.bot.commands.keys():
            await self.bot.say("That is already a standard command.")
            return
        if not self.c_commands:
            self.c_commands = {}
        cmdlist = self.c_commands
        if command not in cmdlist:
            cmdlist[command] = text
            dataIO.save_json(self.file_path, self.c_commands)
            await self.bot.say("PAD command successfully added.")
        else:
            await self.bot.say("This command already exists. Use editpad to edit it.")

    @padglobal.command(pass_context=True)
    async def edit(self, ctx, command : str, *, text):
        """Edits a PAD global command

        Example:
        !padglobal edit yourcommand Text you want
        """
        if not self.settings.checkAdmin(ctx.message.author.id):
            await self.bot.say(inline("Not authorized to edit pad global commands"))
            return

        command = command.lower()
        cmdlist = self.c_commands
        if command in cmdlist:
            cmdlist[command] = text
            dataIO.save_json(self.file_path, self.c_commands)
            await self.bot.say("PAD command successfully edited.")
        else:
            await self.bot.say("PAD command doesn't exist. Use addpad [command] [text]")

    @padglobal.command(pass_context=True)
    async def delete(self, ctx, command : str):
        """Deletes a PAD global command

        Example:
        !padglobal delete yourcommand"""
        if not self.settings.checkAdmin(ctx.message.author.id):
            await self.bot.say(inline("Not authorized to edit pad global commands"))
            return

        command = command.lower()
        cmdlist = self.c_commands
        if command in cmdlist:
            cmdlist.pop(command, None)
            dataIO.save_json(self.file_path, self.c_commands)
            await self.bot.say("PAD command successfully deleted.")
        else:
            await self.bot.say("PAD command doesn't exist.")

    @commands.command(pass_context=True)
    async def pad(self, ctx):
        """Shows PAD global command list"""
        cmdlist = self.c_commands
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
        msg = "Global PAD commands:\n"
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
          'admins' : []
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
