import asyncio
from collections import defaultdict
from enum import Enum
import http.client
import json
import os
import random
import re
import threading
import time
import traceback
import urllib.parse

import discord
from discord.ext import commands

from __main__ import user_allowed, send_cmd_help

from .rpadutils import *
from .utils import checks
from .utils.chat_formatting import *
from .utils.cog_settings import *
from .utils.dataIO import fileIO
from .utils.twitter_stream import *

GETMIRU_HELP = """
**Miru Bot now has a twin sister, also called Miru Bot (public)!**
The new public Miru is open for invite to any server: personal, private, secret-handshake-entry-only, etc
Unlike the private Miru used by larger community servers, public Miru has lower stability requirements, so I will install a variety of random entertainment plugins.

To invite public Miru to your server, use the following link:
https://discordapp.com/oauth2/authorize?client_id=296443771229569026&scope=bot

The following commands might come in handy:
`^modhelp`       - information on how to set up Miru's moderation commands
`^userhelp`     - a user-focused guide to Miru's commands
`^help`             - the full list of Miru commands

A link to the awakenings emoji pack is included in `^modhelp`

If you want to be notified of updates to Miru, suggest features, or ask for help, join the Miru Support server:
https://discord.gg/zB4QHgn(edited)
"""

USER_HELP = """
Bot user help
This command gives you an overview of the most commonly used user-focused
commands, with an emphasis on the ones unique to this bot.

Join the Miru Support Server for info, update, and bot support:
https://discord.gg/zB4QHgn

Use ^help to get a full list of help commands. Execute any command with no
arguments to get more details on how they work.

Info commands:
^credits   some info about the bot
^donate    info on how to donate to cover hosting fees
^userhelp  this message
^modhelp   bot help specifically for mods

General:
^pad             lists the pad-specific global commands
^padfaq          lists pad-specific FAQ commands
^boards          lists common leader optimal board commands
^glossary        looks up a pad term in the glossary
^customcommands  lists the custom commands added by the administrators of your server
^memes           works the same way, but is restricted per-server to a privileged memer-only group
^serverinfo      stats for the current server
^userinfo        stats for a specific user

Events:
^[events|eventsna]  Prints pending/active PAD events for NA
^eventsjp           Prints pending/active PAD events for JP

Monster Info:
^id        search for a monster by ID, full name, nickname, etc
^idz       text-only version if id (the legacy version, for mobile users)
^helpid    gets more info on how monster lookup works, including the nickname submission link
^pantheon  given a monster, print all the members of the pantheon
^pic       prints a link to a a monster image on puzzledragonx, which discord will inline
^img       same as pic

REM Simulation:
^remlist     lists all the REMs available
^reminfo     lists info for a specific REM
^rollrem     simulate a roll for a REM
^rollremfor  roll a REM until you get the desired monster

Profile:
Miru will store your personal PAD details, and provide them on request.
Use the series of commands starting with ^profile to configure your own profile.

Use one of the following commands to retrieve data.
^idme            print your profile to the current channel
^idfor           get profile data for a specific user
^idto            have Miru DM your profile to a user
^profile search  search the list of configured (visible) profiles

Time conversion:
^time    get the current time in a different timezone
^timeto  calculate the how long until another time in another timezone

Translation:
^[jpen|jpus|jaen|jaus] <text>  translate text from japanese to english
"""

MOD_HELP = """
Bot Moderator Help
~~~~~~~~~~~~~~~~~~~~~~

If you need help setting your server up, feel free to ping me (tactical_retreat).

Miru is a set of plugins inside the Red Discord bot, running on discord.py. There
are some custom ones, but a lot of them are generic to all Red Discord bots, so
things you've used elsewhere will probably also work here.

If there is a feature you're missing, let me know and I can check to see if it's
already available in some public plugin. If not, and I think it's valuable, I might
write it.

~~~~~~~~~~~~~~~~~~~~~~

If you would like to add the awakening emojis to your server, upload the icons
in the link (don't change their names) and Miru will automatically begin
using them:
https://drive.google.com/drive/folders/0B4BJOUE5gL0USS12a1BnS1pPMkE?usp=sharing

Contact me if you need help evading the 50 emoji limit.

~~~~~~~~~~~~~~~~~~~~~~

Check out the ^help command from inside your server. You'll see a wider list of
commands than normal users do.

If you've just added Miru to your server, start with the ^modset command. You
might want to configure an Admin and a Mod role (they can be the same thing).

~~~~~~~~~~~~~~~~~~~~~~
Interesting features
~~~~~~~~~~~~~~~~~~~~~~

Twitter:
If you'd like a twitter feed mirrored in your server, contact tactical_retreat

Self applied roles:
You can configure which roles a user can add to themself using ^selfrole via ^adminset

Message logs:
Discord doesn't save deleted/edited messages anywhere. Using ^exlog you can pull
messages for a user, channel, or search for a term.

Contrast this with ^logs which uses the Discord API, and can retrieve a significantly
larger log history, but it reflects what you would see in Discord by scrolling back.

Auto Moderation:
The ^automod2 command allows you to configure a set of rules (defined as regular expressions)
that match messages. You can then apply these rules as either a blacklist or a whitelist to
a specific channel. This allows you to force users to format their messages a specific way,
or to prevent them from saying certain things (the bot deletes violators, and notifies them
via DM).

Bad user tools:
Allows you to specify a set of roles that are applied as punishments to users, generally
restricting them from seeing or speaking in certain channels. If a punishment role is
applied to a user, the last 10 things they said (and where they said it) are recorded, and
a strike is added to their record.

You can configure a channel where Miru will log when these moderation events occur, and ping
@here asking for an explanation. She will also track when a user with a strike leaves the
server, and when they rejoin the server (as this is generally done to evade negative roles).

Custom commands:
Miru supports three types of custom commands, you can find the list of associated commands via ^help.
* CustomCommands: Added by server mods, executable by anyone
* Memes: Added by server mods, executable only by people with a specific Role (configured by mods)
* Pad: Added by specific users (configured by tactical_retreat) and executable by users in any server

PAD Event announcement:
You can use the ^padevents commands to configure PAD related announcements for specific channels.

Using '^padevents addchannel NA' you can enable guerrilla announcements for the current channel.
Using '^padevents addchanneldaily NA' you can enable a dump of the currently active events,
including things like skillup rate, daily descends, daily guerrillas, etc. This typically ticks
over twice daily.

Use the rmchannel* commands to disable those subscriptions. ^padevents listchannels shows the
set of subscriptions for the current server. You can also subscribe to JP events if desired.

Limiting command execution:
The '^p' command can be used to prevent users from executing specific commands on the server,
in specific channels, or unless they have specific roles. Read the documentation carefully.
"""

class TrUtils:
    def __init__(self, bot):
        self.bot = bot
        self.settings = TrUtilsSettings("trutils")
        self.colors = [
           discord.Color.blue(),
           discord.Color.dark_blue(),
           discord.Color.dark_gold(),
           discord.Color.dark_green(),
           discord.Color.dark_grey(),
           discord.Color.dark_magenta(),
           discord.Color.dark_orange(),
           discord.Color.dark_purple(),
           discord.Color.dark_red(),
           discord.Color.dark_teal(),
           discord.Color.darker_grey(),
           discord.Color.default(),
           discord.Color.gold(),
           discord.Color.green(),
           discord.Color.light_grey(),
           discord.Color.lighter_grey(),
           discord.Color.magenta(),
           discord.Color.orange(),
           discord.Color.purple(),
           discord.Color.red(),
           discord.Color.teal(),
       ]

    def registerTasks(self, event_loop):
        print("registering tasks")
        self.rainbow_task = event_loop.create_task(self.refresh_rainbow())

    def __unload(self):
        print("unloading trutils")
        self.rainbow_task.cancel()

    async def refresh_rainbow(self):
        while "TrUtils" in self.bot.cogs:
            try:
                await asyncio.sleep(10)
            except Exception as e:
                print("refresh rainbow loop caught exception " + str(e))
                raise e

            try:
                await self.doRefreshRainbow()
            except Exception as e:
                traceback.print_exc()
                print("caught exception while refreshing rainbow " + str(e))

        print("done refresh_rainbow")

    async def doRefreshRainbow(self):
        servers = self.settings.servers()
        for server_id, server_data in servers.items():
            server = get_server_from_id(self.bot, server_id)
            rainbow_ids = self.settings.rainbow(server_id)
            for role_id in rainbow_ids:
                role = get_role_from_id(self.bot, server, role_id)
                color = random.choice(self.colors)
                try:
                    await self.bot.edit_role(server, role, color=color)
                except Exception as e:
                    traceback.print_exc()
                    print("caught exception while updating role, disabling: " + str(e))
                    self.settings.clearRainbow(server_id, role_id)

    async def on_ready(self):
        """ready"""
        print("started trutils")

    async def check_for_nickname_change(self, before, after):
        try:
            server = after.server
            saved_nick = self.settings.getNickname(server.id, after.id)
            if saved_nick is None:
                return

            if not len(saved_nick):
                saved_nick = None

            if before.nick != after.nick:
                if after.nick != saved_nick:
                    print("caught bad nickname change {} {}".format(after.nick, saved_nick))
                    await self.bot.change_nickname(after, saved_nick)
        except Exception as e:
            traceback.print_exc()
            print('failed to check for nickname change' + str(e))

    @commands.command(pass_context=True)
    async def revertname(self, ctx):
        """Unsets your nickname"""
        await self.bot.change_nickname(ctx.message.author, None)
        await self.bot.say(inline('Done'))

    @commands.command(pass_context=True)
    async def dumpmsg(self, ctx, msg_id : int):
        """Given an ID for a message printed in the current channel, dumps it boxed with formatting escaped"""
        msg = await self.bot.get_message(ctx.message.channel, msg_id)
        content = msg.clean_content.strip()
        if content.startswith('```') or content.endswith('```'):
            content = '`\n{}\n`'.format(content)
        else:
            content = box(content)
        await self.bot.say(content)

    @commands.command(name="dontchangemyname", pass_context=True, no_pm=True)
    @checks.is_owner()
    async def dontchangemyname(self, ctx, nickname):
        self.settings.setNickname(ctx.message.server.id, ctx.message.author.id, nickname)
        await self.bot.say('`done`')

    @commands.command(name="cleardontchangemyname", pass_context=True, no_pm=True)
    @checks.is_owner()
    async def cleardontchangemyname(self, ctx):
        self.settings.clearNickname(ctx.message.server.id, ctx.message.author.id)
        await self.bot.say('`done`')

    @commands.command(name="rainbow", pass_context=True, no_pm=True)
    @checks.is_owner()
    async def rainbow(self, ctx, role_name):
        role = get_role(ctx.message.server.roles, role_name)
        self.settings.setRainbow(ctx.message.server.id, role.id)
        await self.bot.say('`done`')

    @commands.command(name="clearrainbow", pass_context=True, no_pm=True)
    @checks.is_owner()
    async def clearrainbow(self, ctx, role_name):
        role = get_role(ctx.message.server.roles, role_name)
        self.settings.clearRainbow(ctx.message.server.id, role.id)
        await self.bot.say('`done`')

    @commands.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def imagecopy(self, ctx, source_channel : discord.Channel, dest_channel : discord.Channel):
        self.settings.setImageCopy(ctx.message.server.id, source_channel.id, dest_channel.id)
        await self.bot.say('`done`')

    @commands.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def clearimgcopy(self, ctx, channel : discord.Channel):
        self.settings.clearImageCopy(ctx.message.server.id, channel.id)
        await self.bot.say('`done`')

    async def on_imgcopy_message(self, message):
        if message.author.id == self.bot.user.id or message.channel.is_private:
            return

        img_url = extract_image_url(message)
        if img_url is None:
            return

        img_copy_channel_id = self.settings.getImageCopy(message.server.id, message.channel.id)
        if img_copy_channel_id is None:
            return

        embed = discord.Embed()
        embed.set_footer(text='Posted by {} in {}'.format(message.author.name, message.channel.name))
        embed.set_image(url=img_url)

        try:
            await self.bot.send_message(discord.Object(img_copy_channel_id), embed=embed)
        except Exception as e:
            print('Failed to copy msg to', img_copy_channel_id, e)

    @commands.command()
    async def getmiru(self):
        """Tells you how to get Miru into your server"""
        for page in pagify(GETMIRU_HELP, delims=['\n'], shorten_by=8):
            await self.bot.whisper(box(page))

    @commands.command()
    async def userhelp(self):
        """Shows a summary of the useful user features"""
        for page in pagify(USER_HELP, delims=['\n'], shorten_by=8):
            await self.bot.whisper(box(page))

    @commands.command()
    @checks.mod_or_permissions(manage_server=True)
    async def modhelp(self):
        """Shows a summary of the useful moderator features"""
        for page in pagify(MOD_HELP, delims=['\n'], shorten_by=8):
            await self.bot.whisper(box(page))

    @commands.command()
    async def credits(self):
        """Shows info about this bot"""
        author_repo = "https://github.com/Twentysix26"
        red_repo = author_repo + "/Red-DiscordBot"
        rpad_invite = "https://discord.gg/pad"

        about = (
            "This is an instance of [the Red Discord bot]({}), "
            "use the 'info' command for more info. "
            "The various PAD related cogs were created by tactical_retreat. "
            "This bot was created for the [PAD subreddit discord]({}) but "
            "is available for other servers on request."
            "".format(red_repo, rpad_invite))

        baby_miru_url = "http://www.pixiv.net/member_illust.php?illust_id=57613867&mode=medium"
        baby_miru_author = "BOW @ Pixiv"
        cute_miru_url = "https://www.dropbox.com/s/0wlfx3g4mk8c8bg/Screenshot%202016-12-03%2018.39.37.png?dl=0"
        cute_miru_author = "Pancaaake18 @ the MantasticPAD server on discord"
        cute_miru_url = "https://www.dropbox.com/s/0wlfx3g4mk8c8bg/Screenshot%202016-12-03%2018.39.37.png?dl=0"
        cute_miru_author = "Pancaaake18 on discord"
        bot_miru_url = "https://puu.sh/urTm8/c3bdf993bd.png"
        bot_miru_author = "graps on discord"
        avatar = (
            "Bot avatars supplied by:\n"
            "\t[Baby Miru]({}): {}\n"
            "\t[Cute Miru]({}): {}\n"
            "\t[Bot Miru]({}): {}"
            "".format(baby_miru_url, baby_miru_author,
                      cute_miru_url, cute_miru_author,
                      bot_miru_url, bot_miru_author))

        using = (
             "You can use `^help` to get a full list of commands.\n"
             "Use `^userhelp` to get a summary of useful user features.\n"
             "Use `^modhelp` to get info on moderator-only features."
        )

        embed = discord.Embed()
        embed.add_field(name="Instance owned by", value='tactical_retreat')
        embed.add_field(name="About the bot", value=about, inline=False)
        embed.add_field(name="Using the bot", value=using, inline=False)
        embed.add_field(name="Avatar credits", value=avatar, inline=False)
        embed.set_thumbnail(url=self.bot.user.avatar_url)

        try:
            await self.bot.say(embed=embed)
        except discord.HTTPException:
            await self.bot.say("I need the `Embed links` permission "
                               "to send this")

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def supersecretdebug(self, ctx, *, code):
        await self._superdebug(ctx, code=code)
        await self.bot.delete_message(ctx.message)

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def superdebug(self, ctx, *, code):
        """Evaluates code"""
        await self._superdebug(ctx, code=code)

    async def _superdebug(self, ctx, *, code):
        def check(m):
            if m.content.strip().lower() == "more":
                return True

        author = ctx.message.author
        channel = ctx.message.channel

        code = code.strip('` ')
        result = None

        global_vars = globals().copy()
        global_vars['bot'] = self.bot
        global_vars['ctx'] = ctx
        global_vars['message'] = ctx.message
        global_vars['author'] = ctx.message.author
        global_vars['channel'] = ctx.message.channel
        global_vars['server'] = ctx.message.server

        local_vars = locals().copy()
        local_vars['to_await'] = list()

        try:
            eval(compile(code, '<string>', 'exec'), global_vars, local_vars)
            to_await = local_vars['to_await']
        except Exception as e:
            await self.bot.say(box('{}: {}'.format(type(e).__name__, str(e)),
                                   lang="py"))
            return

        for result in to_await:
            if asyncio.iscoroutine(result):
                result = await result

def setup(bot):
    print('trutils bot setup')
    n = TrUtils(bot)
    n.registerTasks(asyncio.get_event_loop())
    bot.add_listener(n.check_for_nickname_change, "on_member_update")
    bot.add_listener(n.on_imgcopy_message, "on_message")
    bot.add_cog(n)
    print('done adding trutils bot')


class TrUtilsSettings(CogSettings):
    def make_default_settings(self):
        config = {
          'servers': {},
        }
        return config

    def servers(self):
        return self.bot_settings['servers']

    def getServer(self, server_id):
        servers = self.servers()
        if server_id not in servers:
            servers[server_id] = {}
        return servers[server_id]

    def setNickname(self, server_id, user_id, nickname):
        server = self.getServer(server_id)
        server[user_id] = nickname
        self.save_settings()

    def getNickname(self, server_id, user_id):
        server = self.getServer(server_id)
        return server.get(user_id)

    def clearNickname(self, server_id, user_id):
        server = self.getServer(server_id)
        if user_id in server:
            server.pop(user_id)
        self.save_settings()

    def rainbow(self, server_id):
        server = self.getServer(server_id)
        if 'rainbow' not in server:
            server['rainbow'] = []
        return server['rainbow']

    def setRainbow(self, server_id, role_id):
        rainbow = self.rainbow(server_id)
        if role_id not in rainbow:
            rainbow.append(role_id)
            self.save_settings()

    def clearRainbow(self, server_id, role_id):
        rainbow = self.rainbow(server_id)
        if role_id in rainbow:
            rainbow.remove(role_id)
            self.save_settings()

    def imagecopy(self, server_id):
        server = self.getServer(server_id)
        if 'imgcopy' not in server:
            server['imgcopy'] = {}
        return server['imgcopy']

    def setImageCopy(self, server_id, source_channel_id, dest_channel_id):
        imagecopy = self.imagecopy(server_id)
        imagecopy[source_channel_id] = dest_channel_id
        self.save_settings()

    def getImageCopy(self, server_id, channel_id):
        imagecopy = self.imagecopy(server_id)
        return imagecopy.get(channel_id)

    def clearImageCopy(self, server_id, channel_id):
        imagecopy = self.imagecopy(server_id)
        if user_id in imagecopy:
            imagecopy.pop(channel_id)
        self.save_settings()

