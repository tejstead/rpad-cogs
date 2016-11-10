import http.client
import urllib.parse
import json
import re

import os

import time
from datetime import datetime
from datetime import timedelta
from dateutil import tz
import pytz
import traceback


import time
import threading
import asyncio
import discord

from enum import Enum

from discord.ext import commands
from .utils.chat_formatting import *
from .utils.dataIO import fileIO
from .utils import checks
from .utils.twitter_stream import *
from __main__ import user_allowed, send_cmd_help

from collections import defaultdict
# from copy import deepcopy

from .utils.cog_settings import *

import prettytable

def normalizeServer(server):
    server = server.upper().strip()
    return 'NA' if server == 'US' else server

SUPPORTED_SERVERS = ["NA", "KR", "JP", "EU"]

def validateAndCleanId(id):
    id = id.replace('-', '').replace(' ', '').replace(',', '').replace('.', '').strip()
    if re.match(r'^\d{9}$', id):
        return id
    else:
        return None
    
def formatId(id):
    return id[0:3] + "," + id[3:6] + "," + id[6:9] + " Group {} (NA) {} (JP)".format(computeOldGroup(id), computeNewGroup(id))

def computeOldGroup(str_id):
    old_id_digit = str_id[2]
    return chr(ord('A') + (int(old_id_digit) % 5))

def computeNewGroup(str_id):
    int_id = int(str_id)
    return (int_id % 3) + 1

class Profile:
    def __init__(self, bot):
        self.bot = bot
        self.settings = ProfileSettings("profile")
        
    async def on_ready(self):
        """ready"""
        print("started profile")
        
        
    @commands.command(name="idme", pass_context=True)
    async def idMe(self, ctx, server=None):
        """idme [server]
        
        Prints out your profile to the current room. If you do not provide a server, your default is used 
        """
        if not await self.settings.checkUsage(ctx, 'idme'):
            return
        
        user_id = ctx.message.author.id
        if server is None:
            server = self.settings.getDefaultServer(user_id)
        server = normalizeServer(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say(inline('Unsupported server: ' + server))
            return
        
        pad_id = self.settings.getId(user_id, server)
        pad_name = self.settings.getName(user_id, server)
        profile_text = self.settings.getProfileText(user_id, server)
        
        line1 = "Info for " + ctx.message.author.name
        line2 = "[{}]: '{}' : {}".format(server, pad_name, formatId(pad_id))
        line3 = profile_text
        
        msg = inline(line1) + "\n" + box(line2 + "\n" + line3)
        await self.bot.say(msg)

    @commands.command(name="idto", pass_context=True)
    async def idTo(self, ctx, user: discord.Member, server=None):
        """idto <user> [server]
        
        Prints out your profile to specified user. If you do not provide a server, your default is used 
        """
        if not await self.settings.checkUsage(ctx, 'idto'):
            return
        profile_msg = await self.getIdMsg(ctx, ctx.message.author, server)
        if profile_msg is None:
            return
        
        warning = inline("{} asked me to send you this message. Report any harassment to the mods.".format(ctx.message.author.name))
        msg = warning + "\n" + profile_msg 
        await self.bot.send_message(user, msg)
        await self.bot.whisper(inline("Sent your profile to " + user.name))

    @commands.command(name="idfor", pass_context=True)
    async def idFor(self, ctx, user: discord.Member, server=None):
        """idfor <user> [server]
        
        Prints out the profile of the specified user. If you do not provide a server, your default is used 
        """
        if not await self.settings.checkUsage(ctx, 'idto'):
            return
        profile_msg = await self.getIdMsg(ctx, user, server)
        if profile_msg is None:
            return
        
        await self.bot.whisper(profile_msg)
    
    
    async def getServer(self, ctx, server=None):
        user_id = ctx.message.author.id
        if server is None:
            server = self.settings.getDefaultServer(user_id)
        server = normalizeServer(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say(inline('Unsupported server: ' + server))
            return None
        return server
    
    async def getIdMsg(self, ctx, user, server=None):
        server = await self.getServer(ctx, server)
        if server is None:
            return None
        
        if not self.settings.getPublic(user.id, server):
            await self.bot.say(inline("That user's profile is private"))
            return None

        pad_id = formatId(self.settings.getId(user.id, server))
        pad_name = self.settings.getName(user.id, server)
        profile_text = self.settings.getProfileText(user.id, server)
        
        line1 = "Info for " + user.name
        line2 = "[{}]: '{}' : {}".format(server, pad_name, pad_id)
        line3 = profile_text
        
        msg = inline(line1) + "\n" + box(line2 + "\n" + line3)
        return msg

    @commands.group(pass_context=True)
    async def profile(self, ctx):
        """Manage profile storage
        
        Whitelist/Blacklist groups are ['idme', 'idto', 'setup'].
        """
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)
            
    @profile.command(name="addwhitelist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addwhitelist(self, ctx, group):
        await self.settings.addToWhitelist(ctx, group)
            
    @profile.command(name="rmwhitelist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmwhitelist(self, ctx, group):
        await self.settings.removeFromWhitelist(ctx, group)
            
    @profile.command(name="addblacklist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def addblacklist(self, ctx, group):
        await self.settings.addToBlacklist(ctx, group)
            
    @profile.command(name="rmblacklist", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_server=True)
    async def rmblacklist(self, ctx, group):
        await self.settings.removeFromBlacklist(ctx, group)

    @profile.command(name="server", pass_context=True)
    async def setServer(self, ctx, server):
        """profile server <server>
        
        Sets your default server to one of the supported servers: [NA, EU, JP, KR].
        This server is used to default the idme command if you don't provide a server.
        """
        if not await self.settings.checkUsage(ctx, 'setup'):
            return
        server = normalizeServer(server)
        if server not in SUPPORTED_SERVERS:
            await self.bot.say(inline('Unsupported server: ' + server))
            return
        
        self.settings.setDefaultServer(ctx.message.author.id, server)
        await self.bot.say(inline('Set your default server to: ' + server))

    @profile.command(name="id", pass_context=True)
    async def setId(self, ctx,  server, *id):
        """profile id <server> <id>
        
        Sets your ID for a server. ID must be 9 digits, can be space/comma/dash delimited.
        """
        if not await self.settings.checkUsage(ctx, 'setup'):
            return
        server = await self.getServer(ctx, server)
        if server is None:
            return None
        
        id = " ".join(id)
        clean_id = validateAndCleanId(id)
        if clean_id is None:
            await self.bot.say(inline('Your ID looks invalid, expected a 9 digit code, got: {}'.format(id)))
            return    
        
        self.settings.setId(ctx.message.author.id, server, clean_id)
        await self.bot.say(inline('Set your id for {} to: {}'.format(server, formatId(clean_id))))
        
    @profile.command(name="name", pass_context=True)
    async def setName(self, ctx,  server, *name):
        """profile name <server> <name>
        
        Sets your in game name for a server.
        """
        if not await self.settings.checkUsage(ctx, 'setup'):
            return
        server = await self.getServer(ctx, server)
        if server is None:
            return None
        
        name = " ".join(name)
        self.settings.setName(ctx.message.author.id, server, name)
        await self.bot.say(inline('Set your name for {} to: {}'.format(server, name)))
        
    @profile.command(name="text", pass_context=True)
    async def setText(self, ctx, server, *text):
        """profile text <server> <profile text>
        
        Sets your profile text for the server, used by the idme command and search.
        """
        if not await self.settings.checkUsage(ctx, 'setup'):
            return
        
        server = await self.getServer(ctx, server)
        if server is None:
            return None
        
        text = " ".join(text).strip()
        
        if text == '':
            await self.bot.say(inline('Profile text required'))
            return
            
        self.settings.setProfileText(ctx.message.author.id, server, text)
        await self.bot.say(inline('Set your profile for ' + server + ' to:\n' + text))
        
    @profile.command(name="clear", pass_context=True)
    async def clear(self, ctx, server=None):
        """profile clear [server]
        
        Deletes your saved profile for a server, or if no server is provided then all profiles.
        """
        if not await self.settings.checkUsage(ctx, 'setup'):
            return
        user_id = ctx.message.author.id
        if server is None:
            self.settings.clearProfile(user_id)
            await self.bot.say(inline('Cleared your profile for all servers'))
        else:
            server = normalizeServer(server)
            self.settings.clearProfile(user_id, server)
            await self.bot.say(inline('Cleared your profile for ' + server))
        
    @profile.command(name="visibility", pass_context=True)
    async def visibility(self, ctx, visibility, server=None):
        """profile visibility <public|private> [server]
        
        Toggle the visibility of your profile. If your profile is private, users will not be able
        to find you via search or idfor. The only data users can access are things you have
        provided via profile commands.
        """
        if not await self.settings.checkUsage(ctx, 'setup'):
            return
        
        server = await self.getServer(ctx, server)
        if server is None:
            return None
        
        visibility = visibility.lower()
        if visibility in ['public', 'private']:
            user_id = ctx.message.author.id
            self.settings.setPublic(user_id, server, visibility == 'public')
            await self.bot.say(inline('Your profile visibility on {} is now : {}'.format(server, visibility)))
        else:
            await self.bot.say(inline('Visibility must be one of [public, private] but got : ' + visibility))

    @profile.command(name="search", pass_context=True, no_pm=False)
    async def search(self, ctx, server, *search_text):
        """profile search <server> <search text>
        
        Scans all public profiles for the search text and PMs the results.
        """
        if not await self.settings.checkUsage(ctx, 'setup'):
            return
        server = await self.getServer(ctx, server)
        if server is None:
            return None
        
        search_text = " ".join(search_text).strip().lower()
        if search_text == '':
            await self.bot.say(inline('Search text required'))
            return
        
        # Get all profiles for server
        profiles = [p[server] for p in self.settings.profiles().values() if server in p]
        # Limit to just the public ones
        profiles = filter(lambda p: p.get('public', True), profiles)
        # Eliminate profiles without an ID set
        profiles = filter(lambda p: 'id' in p, profiles)
        profiles = list(profiles)
        
        # Match the public profiles against the search text
        matching_profiles = filter(lambda p: search_text in p.get('text', '').lower(), profiles)
        matching_profiles = list(matching_profiles)
        
        template = 'Found {}/{} matching profiles in {} for : {}'
        msg = template.format(len(matching_profiles), len(profiles), server, search_text)
        await self.bot.say(inline(msg))
        
        if len(matching_profiles) == 0:
            return
        
        msg = 'Displaying {} matches for server {}:\n'.format(len(matching_profiles), server)
        for p in matching_profiles:
            pad_id = formatId(p['id'])
            pad_name = p.get('name', 'unknown')
            profile_text = p['text']
        
            line1 = "'{}' : {}".format(pad_name, pad_id)
            line2 = profile_text
            msg = msg + line1 + "\n" + line2 + "\n\n"
        
        await self.pageOutput(msg)
        
    async def pageOutput(self, msg):
        msg = msg.strip()
        msg = pagify(msg, ["\n"], shorten_by=20)
        for page in msg:
            try:
                await self.bot.whisper(box(page))
            except Exception as e:
                print("page output failed " + str(e))
                print("tried to print: " + page)

def setup(bot):
    print('profile bot setup')
    n = Profile(bot)
    bot.add_cog(n)
    print('done adding profile bot')


class ProfileSettings(CogSettings):
    def make_default_settings(self):
        config = {
          'default_servers': {},
          'user_profiles': {},
        }
        return config
    
    def profiles(self):
        return self.bot_settings['user_profiles']

    def default_server(self):
        return self.bot_settings['default_servers']
    
    def setDefaultServer(self, user, server):
        self.default_server()[user] = server
        self.save_settings()

    def getDefaultServer(self, user):
        return self.default_server().get(user, 'NA')
    
    def getProfile(self, user, server):
        profiles = self.profiles()
        if user not in profiles:
            profiles[user] = {}
        profile = profiles[user]
        if server not in profile:
            profile[server] = {}
        return profile[server]
    
    def setId(self, user, server, id):
        self.getProfile(user, server)['id'] = id
        self.save_settings()

    def getId(self, user, server):
        return self.getProfile(user, server).get('id', '000000000')
    
    def setPublic(self, user, server, is_public):
        self.getProfile(user, server)['public'] = is_public
        self.save_settings()

    def getPublic(self, user, server):
        return self.getProfile(user, server).get('public', True)
        
    def setName(self, user, server, name):
        self.getProfile(user, server)['name'] = name
        self.save_settings()


    def getName(self, user, server):
        return self.getProfile(user, server).get('name', 'name not set')
    
    def setProfileText(self, user, server, text):
        self.getProfile(user, server)['text'] = text
        self.save_settings()

    def getProfileText(self, user, server):
        return self.getProfile(user, server).get('text', 'profile text not set')

    def clearProfile(self, user, server=None):
        if server is None:
            self.profiles().remove(user)
        else:
            self.getProfile(user, server).clear()
        self.save_settings()
