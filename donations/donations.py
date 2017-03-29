from collections import defaultdict
import difflib
import os
import re

import discord
from discord.ext import commands
from numpy.doc import glossary

from __main__ import user_allowed, send_cmd_help

from .rpadutils import *
from .utils import checks
from .utils.cog_settings import *
from .utils.dataIO import dataIO


DONATE_MSG = """
To donate to cover bot hosting fees you can use one of:
  Patreon : https://www.patreon.com/miru_bot
  Venmo   : https://venmo.com/Tactical-Retreat

Read the Patreon or join the Miru Support Server for more details:
  https://discord.gg/zB4QHgn

You permanently get some special perks for donating even $1.

The following users have donated. Thanks!
{donors}
"""

class Donations:
    """Manages donations and perks."""

    def __init__(self, bot):
        self.bot = bot
        self.settings = DonationsSettings("donations")

    @commands.command(pass_context=True)
    async def donate(self, ctx):
        """Prints information about donations."""
        donors = self.settings.donors()
        donor_names = set()
        for user in self.bot.get_all_members():
            if user.id in donors:
                donor_names.add(user.name)

        msg = DONATE_MSG.format(count=len(donors), donors=', '.join(sorted(donor_names)))
        await self.bot.say(box(msg))

    @commands.command(pass_context=True)
    async def mycommand(self, ctx, command : str, *, text : str):
        """Sets your custom command (donor only)."""
        user_id = ctx.message.author.id
        if user_id not in self.settings.donors():
            await self.bot.say(inline('Only donors can set a personal command'))
            return

        self.settings.addCustomCommand(user_id, command, text)
        await self.bot.say(inline('I set up your command: ' + command))

    @commands.command(pass_context=True)
    async def myembed(self, ctx, command : str, title : str, url : str, footer : str):
        """Sets your custom embed command (donor only).

        This lets you create a fancier image message. For example you can set up
        a simple inline image without a link using:
        ^myembed lewd "" "http://i0.kym-cdn.com/photos/images/original/000/731/885/751.jpg" ""

        Want a title on that image? Fill in the first argument:
        ^myembed lewd "L-lewd!" "<snip, see above>" ""

        Want a footer? Fill in the last argument:
        ^myembed lewd "L-lewd!" "<snip, see above>" "source: some managa i read"
        """
        user_id = ctx.message.author.id
        if user_id not in self.settings.donors():
            await self.bot.say(inline('Only donors can set a personal command'))
            return

        self.settings.addCustomEmbed(user_id, command, title, url, footer)
        await self.bot.say(inline('I set up your embed: ' + command))

    @commands.group(pass_context=True)
    @checks.admin_or_permissions(manage_server=True)
    async def donations(self, context):
        """Manage donation options."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    @donations.command(pass_context=True)
    @checks.admin_or_permissions(manage_server=True)
    async def togglePerks(self, ctx):
        """Enable or disable donor-specific perks for the server."""
        server_id = ctx.message.server.id
        if server_id in self.settings.disabledServers():
            self.settings.rmDisabledServer(server_id)
            await self.bot.say(inline('Donor perks enabled on this server'))
        else:
            self.settings.addDisabledServer(server_id)
            await self.bot.say(inline('Donor perks disabled on this server'))

    @donations.command(pass_context=True)
    @checks.is_owner()
    async def addDonor(self, ctx, user : discord.User):
        """Adds a a user as a donor."""
        self.settings.addDonor(user.id)
        await self.bot.say(inline('Done'))

    @donations.command(pass_context=True)
    @checks.is_owner()
    async def rmDonor(self, ctx, user : discord.User):
        """Removes a user as a donor."""
        self.settings.rmDonor(user.id)
        await self.bot.say(inline('Done'))

    @donations.command(pass_context=True)
    @checks.is_owner()
    async def addPatron(self, ctx, user : discord.User):
        """Adds a a user as a patron."""
        self.settings.addPatron(user.id)
        await self.bot.say(inline('Done'))

    @donations.command(pass_context=True)
    @checks.is_owner()
    async def rmPatron(self, ctx, user : discord.User):
        """Removes a user as a patron."""
        self.settings.rmPatron(user.id)
        await self.bot.say(inline('Done'))

    @donations.command(pass_context=True)
    @checks.is_owner()
    async def info(self, ctx):
        """Print donation related info."""
        patrons = self.settings.patrons()
        donors = self.settings.donors()
        cmds = self.settings.customCommands()
        embeds = self.settings.customEmbeds()
        disabled_servers = self.settings.disabledServers()

        id_to_name = {m.id:m.name for m in self.bot.get_all_members()}

        msg = 'Donations Info'

        msg += '\n\nPatrons:'
        for user_id in patrons:
            msg += '\n\t{} ({})'.format(id_to_name.get(user_id, 'unknown'), user_id)

        msg += '\n\nDonors:'
        for user_id in donors:
            msg += '\n\t{} ({})'.format(id_to_name.get(user_id, 'unknown'), user_id)

        msg += '\n\nDisabled servers:'
        for server_id in disabled_servers:
            server = self.bot.get_server(server_id)
            msg += '\n\t{} ({})'.format(server.name if server else 'unknown', server_id)

        msg += '\n\n{} personal commands are set'.format(len(cmds))
        msg += '\n{} personal embeds are set'.format(len(cmds))

        await self.bot.say(box(msg))


    async def checkCC(self, message):
        if len(message.content) < 2:
            return

        prefix = self.get_prefix(message)

        if not prefix:
            return

        user_id = message.author.id
        if user_id not in self.settings.donors():
            return

        if message.server and message.server.id in self.settings.disabledServers():
            return

        user_cmd = self.settings.customCommands().get(user_id)
        user_embed = self.settings.customEmbeds().get(user_id)

        cmd = message.content[len(prefix):].lower()
        if user_cmd is not None:
            if cmd == user_cmd['command']:
                await self.bot.send_message(message.channel, user_cmd['text'])
                return
        if user_embed is not None:
            if cmd == user_embed['command']:
                embed = discord.Embed()
                title = user_embed['title']
                url = user_embed['url']
                footer = user_embed['footer']
                if len(title):
                    embed.title = title
                if len(url):
                    embed.set_image(url=url)
                if len(footer):
                    embed.set_footer(text=footer)
                await self.bot.send_message(message.channel, embed=embed)
                return


    def get_prefix(self, message):
        for p in self.bot.settings.get_prefixes(message.server):
            if message.content.startswith(p):
                return p
        return False

        return command


def setup(bot):
    n = Donations(bot)
    bot.add_listener(n.checkCC, "on_message")
    bot.add_cog(n)


class DonationsSettings(CogSettings):
    def make_default_settings(self):
        config = {
          'patrons' : [],
          'donors' : [],
          'custom_commands' : {},
          'custom_embeds' : {},
          'disabled_servers' : [],
        }
        return config

    def patrons(self):
        return self.bot_settings['patrons']

    def addPatron(self, user_id):
        patrons = self.patrons()
        if user_id not in patrons:
            patrons.append(user_id)
            self.save_settings()

    def rmPatron(self, user_id):
        patrons = self.patrons()
        if user_id in patrons:
            patrons.remove(user_id)
            self.save_settings()

    def donors(self):
        return self.bot_settings['donors']

    def addDonor(self, user_id):
        donors = self.donors()
        if user_id not in donors:
            donors.append(user_id)
            self.save_settings()

    def rmDonor(self, user_id):
        donors = self.donors()
        if user_id in donors:
            donors.remove(user_id)
            self.save_settings()

    def customCommands(self):
        return self.bot_settings['custom_commands']

    def addCustomCommand(self, user_id, command, text):
        cmds = self.customCommands()
        cmds[user_id] = {
            'command' : command.lower(),
            'text' : text,
        }
        self.save_settings()

    def rmCustomCommand(self, user_id):
        cmds = self.customCommands()
        if user_id in cmds:
            cmds.remove(user_id)
            self.save_settings()

    def customEmbeds(self):
        return self.bot_settings['custom_embeds']

    def addCustomEmbed(self, user_id, command, title, url, footer):
        embeds = self.customEmbeds()
        embeds[user_id] = {
            'command' : command.lower().strip(),
            'title' : title.strip(),
            'url' : url.strip(),
            'footer' : footer.strip(),
        }
        self.save_settings()

    def rmCustomEmbed(self, user_id):
        embeds = self.customEmbeds()
        if user_id in embeds:
            embeds.remove(user_id)
            self.save_settings()

    def disabledServers(self):
        return self.bot_settings['disabled_servers']

    def addDisabledServer(self, server_id):
        disabled_servers = self.disabledServers()
        if server_id not in disabled_servers:
            disabled_servers.append(server_id)
            self.save_settings()

    def rmDisabledServer(self, server_id):
        disabled_servers = self.disabledServers()
        if server_id in disabled_servers:
            disabled_servers.remove(server_id)
            self.save_settings()
