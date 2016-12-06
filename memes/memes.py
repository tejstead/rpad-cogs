import discord
from discord.ext import commands
from .utils.dataIO import fileIO
from .utils import checks
from __main__ import user_allowed, send_cmd_help
import os
import re

from .utils.cog_settings import *

class Memes:
    """Custom memes."""

    def __init__(self, bot):
        self.bot = bot
        self.c_commands = fileIO("data/memes/commands.json", "load")
        self.settings = MemesSettings("memes")

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(administrator=True)
    async def addmeme(self, ctx, command : str, *, text):
        """Adds a meme

        Example:
        !addmeme yourmeme Text you want
        """
        server = ctx.message.server
        command = command.lower()
        if command in self.bot.commands.keys():
            await self.bot.say("That meme is already a standard command.")
            return
        if not server.id in self.c_commands:
            self.c_commands[server.id] = {}
        cmdlist = self.c_commands[server.id]
        if command not in cmdlist:
            cmdlist[command] = text
            self.c_commands[server.id] = cmdlist
            fileIO("data/memes/commands.json", "save", self.c_commands)
            await self.bot.say("Custom command successfully added.")
        else:
            await self.bot.say("This command already exists. Use editcom to edit it.")

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(administrator=True)
    async def editmeme(self, ctx, command : str, *, text):
        """Edits a meme

        Example:
        !editmeme yourcommand Text you want
        """
        server = ctx.message.server
        command = command.lower()
        if server.id in self.c_commands:
            cmdlist = self.c_commands[server.id]
            if command in cmdlist:
                cmdlist[command] = text
                self.c_commands[server.id] = cmdlist
                fileIO("data/memes/commands.json", "save", self.c_commands)
                await self.bot.say("Custom command successfully edited.")
            else:
                await self.bot.say("That command doesn't exist. Use addcom [command] [text]")
        else:
             await self.bot.say("There are no custom commands in this server. Use addcom [command] [text]")

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(administrator=True)
    async def delmeme(self, ctx, command : str):
        """Deletes a meme

        Example:
        !delmeme yourcommand"""
        server = ctx.message.server
        command = command.lower()
        if server.id in self.c_commands:
            cmdlist = self.c_commands[server.id]
            if command in cmdlist:
                cmdlist.pop(command, None)
                self.c_commands[server.id] = cmdlist
                fileIO("data/memes/commands.json", "save", self.c_commands)
                await self.bot.say("Custom meme successfully deleted.")
            else:
                await self.bot.say("That meme doesn't exist.")
        else:
            await self.bot.say("There are no custom memes in this server. Use addmeme [command] [text]")

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(administrator=True)
    async def setmemerole(self, ctx, rolename : str):
        """Sets the meme role

        Example:
        !setmemerole Regular"""

        role = self._get_role(ctx.message.server.roles, rolename)
        self.settings.setPrivileged(ctx.message.server.id, role.id)
        await self.bot.say("done")

    @commands.command(pass_context=True, no_pm=True)
    async def memes(self, ctx):
        """Shows custom memes list"""
        server = ctx.message.server
        if server.id in self.c_commands:
            cmdlist = self.c_commands[server.id]
            if cmdlist:
                i = 0
                msg = ["```Custom memes:\n"]
                for cmd in sorted([cmd for cmd in cmdlist.keys()]):
                    if len(msg[i]) + len(ctx.prefix) + len(cmd) + 5 > 2000:
                        msg[i] += "```"
                        i += 1
                        msg.append("``` {}{}\n".format(ctx.prefix, cmd))
                    else:
                        msg[i] += " {}{}\n".format(ctx.prefix, cmd)
                msg[i] += "```"
                for cmds in msg:
                    await self.bot.whisper(cmds)
            else:
                await self.bot.say("There are no custom memes in this server. Use addmeme [command] [text]")
        else:
            await self.bot.say("There are no custom memes in this server. Use addmeme [command] [text]")

    async def checkCC(self, message):
        if message.author.id == self.bot.user.id or len(message.content) < 2 or message.channel.is_private:
            return

        if not user_allowed(message):
            return


        role_id = self.settings.getPrivileged(message.server.id)
        if role_id is not None:
            role = self._get_role_from_id(message.server, role_id)
            if role not in message.author.roles:
                return

        msg = message.content
        server = message.server
        prefix = self.get_prefix(msg)

        if prefix and server.id in self.c_commands.keys():
            cmdlist = self.c_commands[server.id]
            cmd = msg[len(prefix):]
            if cmd in cmdlist.keys():
                cmd = cmdlist[cmd]
                cmd = self.format_cc(cmd, message)
                await self.bot.send_message(message.channel, cmd)
            elif cmd.lower() in cmdlist.keys():
                cmd = cmdlist[cmd.lower()]
                cmd = self.format_cc(cmd, message)
                await self.bot.send_message(message.channel, cmd)

    def get_prefix(self, msg):
        for p in self.bot.command_prefix:
            if msg.startswith(p):
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

    def _get_role(self, roles, role_string):
        if role_string.lower() == "everyone":
            role_string = "@everyone"

        role = discord.utils.find(
            lambda r: r.name.lower() == role_string.lower(), roles)

        if role is None:
            raise RoleNotFound(roles[0].server, role_string)

        return role

    def _get_role_from_id(self, server, roleid):
        try:
            roles = server.roles
        except AttributeError:
            server = self._get_server_from_id(server)
            try:
                roles = server.roles
            except AttributeError:
                raise RoleNotFound(server, roleid)

        role = discord.utils.get(roles, id=roleid)
        if role is None:
            raise RoleNotFound(server, roleid)
        return role

    def _get_server_from_id(self, serverid):
        return discord.utils.get(self.bot.servers, id=serverid)


def check_folders():
    if not os.path.exists("data/memes"):
        print("Creating data/memes folder...")
        os.makedirs("data/memes")

def check_files():
    f = "data/memes/commands.json"
    if not fileIO(f, "check"):
        print("Creating empty commands.json...")
        fileIO(f, "save", {})

def setup(bot):
    check_folders()
    check_files()
    n = Memes(bot)
    bot.add_listener(n.checkCC, "on_message")
    bot.add_cog(n)


class MemesSettings(CogSettings):
    def make_default_settings(self):
        config = {
          'configs' : {}
        }
        return config

    def serverConfigs(self):
        return self.bot_settings['configs']

    def getServer(self, server_id):
        configs = self.serverConfigs()
        if server_id not in configs:
            configs[server_id] = {}
        return configs[server_id]

    def getPrivileged(self, server_id):
        server = self.getServer(server_id)
        return server.get('privileged')

    def setPrivileged(self, server_id, role_id):
        server = self.getServer(server_id)
        server['privileged'] = role_id
        self.save_settings()
