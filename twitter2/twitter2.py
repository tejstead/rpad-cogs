import asyncio
from copy import deepcopy
from datetime import datetime
import os
import threading
import time

from dateutil import tz
import discord
from discord.ext import commands
from twython import Twython, TwythonStreamer
from twython.exceptions import TwythonError

from __main__ import user_allowed, send_cmd_help

from .utils import checks
from .utils.chat_formatting import *
from .utils.dataIO import fileIO
from .utils.twitter_stream import *


TIME_FMT = """%a %b %d %H:%M:%S %Y"""

class TwitterCog2:
    def __init__(self, bot):
        self.bot = bot
        self.config = fileIO("data/twitter2/config.json", "load")

        config = self.config
        self.twitter_config = (config['akey'], config['asecret'], config['otoken'], config['osecret'])
        print(self.twitter_config)

#         self.channels = list() # channels to push updates to
        self.channel_ids = config['channels'] or dict()
        self.ntweets = 0
        self.stream = None
        self.stream_thread = None
        self.pre = 'TwitterBot: '  # message preamble

    def __unload(self):
        # Stop previous thread, if any
        if self.stream_thread:
            self.stream.disconnect()
            self.stream_thread.join()

    async def connect(self):
        """Called when connected as a Discord client. Sets up the TwitterUserStream
and starts following a user if one was set upon construction."""
        print("Connected twitter bot.")
        # Setup twitter stream
        if self.stream:
            print("skipping connect")
            return
        self.stream = TwitterUserStream(self.twitter_config)
        self.stream.add(self.tweet)
        await self.refollow()
        print("done with on_ready")

    @commands.group(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def twitter2(self, ctx):
        """Manage twitter feed mirroring"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @twitter2.command(name="info", pass_context=True, no_pm=True)
    async def _info(self, ctx):
        await self.bot.say(self.info(ctx.message.channel))

#     @twitter2.command(name="follow", pass_context=True, no_pm=True)
#     @checks.mod_or_permissions(manage_server=True)
#     async def _follow(self, ctx, command):
#         await self.bot.say("stopping follow on " + self.tuser)
#         tuser = command
#         self.stream.disconnect()
#         await self.bot.say("starting follow on " + tuser)
#         await self.follow(tuser, ctx.message.channel)

    @twitter2.command(name="addchannel", pass_context=True, no_pm=True)
    async def _addchannel(self, ctx, twitter_user):
        twitter_user = twitter_user.lower()
        already_following = twitter_user in self.channel_ids
        if already_following:
            if ctx.message.channel.id in self.channel_ids[twitter_user]:
                await self.bot.say("Channel already active.")
                return
        elif not self.checkTwitterUser(twitter_user):
            await self.bot.say(inline("User seems invalid : " + twitter_user))
            return
        else:
            self.channel_ids[twitter_user] = list()

        self.channel_ids[twitter_user].append(ctx.message.channel.id)
        self.save_config()
        await self.bot.say(inline("Channel now active for user " + twitter_user))

        if not already_following:
            await self.bot.say(inline("New account, restarting twitter connection"))
            await self.refollow()


    @twitter2.command(name="rmchannel", pass_context=True, no_pm=True)
    async def _rmchannel(self, ctx, twitter_user):
        twitter_user = twitter_user.lower()
        channel_id = ctx.message.channel.id
        if twitter_user not in self.channel_ids:
            await self.bot.say(inline("That account is not active for any channels."))
            return
        elif channel_id not in self.channel_ids[twitter_user]:
            await self.bot.say(inline("Channel was not active for that account."))
            return

        self.channel_ids[twitter_user].remove(channel_id)
        await self.bot.say(inline("Channel removed for user " + twitter_user))
        if not len(self.channel_ids[twitter_user]):
            await self.bot.say(inline("Last channel removed for " + twitter_user + ", restarting twitter connection"))
            self.channel_ids.pop(twitter_user)
            await self.refollow(True)

        self.save_config()

    @twitter2.command(name="resend", pass_context=True, no_pm=True)
    async def _resend(self, ctx, idx : int=1):
        last_tweet = self.stream.last(idx)
        if last_tweet:
            print('Resending tweet idx ' + str(idx))
            await self.tweetAsync(last_tweet)
        else:
            await self.bot.say('No tweet to send')


    def checkTwitterUser(self, tuser):
        return self.stream.get_user(tuser) is not None

    async def refollow(self, src_channel=None):
        """Start streaming tweets from the Twitter user by the given name.
Returns False if the user does not exist, True otherwise."""
        if not len(self.channel_ids):
            return

        # Stop previous thread, if any
        if self.stream_thread:
            if src_channel:
                await self.bot.say("Disconnecting from twitter.")
            self.stream.disconnect()
            self.stream_thread.join()

        # Setup new thread to run the twitter stream in background
        if src_channel:
            await self.bot.say("Connecting to twitter.")

        user_string = ",".join(self.channel_ids.keys())
        self.stream_thread = self.stream.follow_thread(user_string)

        if src_channel:
            await self.bot.say("Now following these users: " + user_string + ".")

    def totime(self, data):
        dt = TwitterUserStream.timeof(data)
        utc = dt.replace(tzinfo=tz.tzutc())
        local = utc.astimezone(tz.tzlocal())
        return local.strftime(TIME_FMT)

    def tweet(self, data):
        self.bot.loop.call_soon(asyncio.async, self.tweetAsync(data))


    @twitter2.command(name="testmsg", pass_context=True, no_pm=True)
    async def _testmsg(self, ctx, twitter_user):
        data = {
            'text' : 'test msg',
            'id_str' : 'idstring',
            'user' : {'screen_name' : twitter_user}
        }
        await self.bot.say("Sending test msg: " + str(data))
        await self.tweetAsync(data)

    async def tweetAsync(self, data):
        """Display a tweet to the current channel. Increments ntweets."""
        text = data and data.get('text')
        msg_id = data and data.get('id_str')
        user = data and data.get('user')
        user_name = user and user.get('screen_name')

        if not text:
            return False

        self.ntweets += 1
        msg = box("@" + user_name + " tweeted : \n" + text)
        msg += "<https://twitter.com/" + user_name + "/status/" + msg_id + ">"

        entities = data.get('entities')
        if entities:
            print("got entities")
            safe_print2(entities)
            media = entities.get('media')
            if media and len(media) > 0:
                print("media")
                msg += "\nImages:"
                for media_item in media:
                    msg += "\n" + media_item.get("media_url_https")

        await self.send_all(msg, user_name)
        return True

    async def send_all(self, message, twitter_user):
        """Send a message to all active channels."""
        twitter_user = twitter_user.lower()
        if twitter_user not in self.channel_ids:
            print("Error! Unexpected user: " + twitter_user)
            return

        for chan_id in self.channel_ids[twitter_user]:
            print("for channel " + chan_id)
            await self.bot.send_message(discord.Object(chan_id), message)
        return True


    def info(self, channel=None):
        """Send the clients some misc info. Only shows channels on the same server
as the given channel. If channel is None, show active channels from all servers."""
        # Get time of last message from following user
        last_time = 'Never'
        if self.stream and self.stream.last():
            last_time = self.totime(self.stream.last())

        # Get the active channels on the same server as the request
        ccount = 0
        cstr = ""
#         for c in self.channels:
#             if channel is None or c.server == channel.server:
#                 ccount += 1
#                 cstr += "#" + c.name + ", "
        if cstr:
            cstr = cstr[:-2]  # strip extra comma


        return ("**TwitterBot**\n" +
                "Currently following: " + ",".join(self.channel_ids.keys()) + "\n" +
                "Tweets streamed: " + str(self.ntweets) + "\n" +
                "Last tweet from user: " + last_time + "\n" +
                "Active channels on server: (" + str(ccount) + ") " + cstr)

    def save_config(self):
        self.config['channels'] = self.channel_ids
        f = "data/twitter2/config.json"
        fileIO(f, "save", self.config)


def check_folder():
    if not os.path.exists("data/twitter2"):
        print("Creating data/twitter2 folder...")
        os.makedirs("data/twitter2")


def check_file():
    config = {
      'akey' : '',
      'asecret' : '',
      'otoken' : '',
      'osecret' : '',
      'channels' : [],
    }

    f = "data/twitter2/config.json"
    if not fileIO(f, "check"):
        print("Creating default twitter2 config.json...")
        fileIO(f, "save", config)


def setup(bot):
    print('twitter2 bot setup')
    check_folder()
    check_file()
    n = TwitterCog2(bot)
    loop = asyncio.get_event_loop()
    loop.create_task(n.connect())
    bot.add_cog(n)
    print('done adding twitter2 bot')

def safe_print2(thing):
    if thing:
        try:
            import json
            print(json.dumps(thing, ensure_ascii=True, sort_keys=True, indent=2, separators=(',', ': ')))
#             print(repr(thing).decode("unicode-escape"))
        except:
            print("failed to pritn")
    else:
        print("null")
