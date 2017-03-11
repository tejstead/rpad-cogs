from collections import defaultdict
from collections import deque
import copy
from io import BytesIO
import os
import os
from subprocess import check_call
import sys
import textwrap
from time import time
from zipfile import ZipFile

import aiohttp
import cv2
import discord
from discord.ext import commands
import np

from __main__ import send_cmd_help
from . import padvision

from .utils import checks
from .utils.chat_formatting import *
from .utils.dataIO import fileIO


DATA_DIR = 'data/padboard'
ORB_DATA_DIR = DATA_DIR + '/orb_images'

LOGS_PER_USER = 5

class PadBoard:
    def __init__(self, bot):
        self.bot = bot
        self.logs = defaultdict(lambda: deque(maxlen=5))
        self.orb_type_to_images = padvision.load_orb_images_dir_to_map(ORB_DATA_DIR)

    async def log_message(self, message):
        self.logs[message.author.id].append(message)

    @commands.group(pass_context=True)
    async def padboard(self, context):
        """PAD board utilities."""
        if context.invoked_subcommand is None:
            await send_cmd_help(context)

    def clear_training_folder(self):
        for f in os.listdir(ORB_DATA_DIR):
            file_path = os.path.join(ORB_DATA_DIR, f)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(e)

    @padboard.command(pass_context=True)
    @checks.is_owner()
    async def downloadtraining(self, ctx, training_zip_url):
        """Replaces the current training set from a new zip file.
        Current path to zip file is https://drive.google.com/uc?export=download&id=0B4BJOUE5gL0UTF9xZnJkVHJYWEU
        """
        await self.bot.say(inline('starting download'))
        async with aiohttp.get(training_zip_url) as r:
            if r.status != 200:
                await self.bot.say(inline('download failed'))
                return

            zipfile_bytes = await r.read()
            zip_file = ZipFile(BytesIO(zipfile_bytes))
            files = zip_file.namelist()

            if len(files) == 0:
                await self.bot.say(inline('empty zip file?'))
                return

            await self.bot.say(box('deleting existing files and unzipping files:\n{}'.format('\n'.join(files))))
            self.clear_training_folder()
            zip_file.extractall(ORB_DATA_DIR)
            await self.bot.say(inline('done extracting'))
            self.orb_type_to_images = padvision.load_orb_images_dir_to_map(ORB_DATA_DIR)
            await self.bot.say(inline('done reloading'))

    def find_image(self, user_id):
        messages = list(self.logs[user_id])
        messages.reverse()
        for m in messages:
            if is_valid_image_url(m.content):
                return m.content
            if len(m.attachments) and is_valid_image_url(m.attachments[0]['url']):
                return m.attachments[0]['url']
        return None

    async def download_image(self, image_url):
        async with aiohttp.get(image_url) as r:
            if r.status == 200:
                image_data = await r.read()
                return image_data
        return None

    @commands.command(pass_context=True)
    async def dawnglare(self, ctx, user: discord.Member=None):
        """Scans your recent messages for images. Attempts to convert the image into a dawnglare link."""
        user_id = user.id if user else ctx.message.author.id
        image_url = self.find_image(user_id)

        if not image_url:
            if user:
                await self.bot.say(inline("Couldn't find an image in that user's recent messages."))
            else:
                await self.bot.say(inline("Couldn't find an image in your recent messages. Upload or link to one and try again"))
            return

        image_data = await self.download_image(image_url)
        if not image_data:
            await self.bot.say(inline("failed to download"))
            return

        result = self.classify_to_string(image_data)
        if 'm' in result:
            if 'j' and 'p' in result:
                await self.bot.say(inline('Warning: mortals not supported by dawnglare, replaced with jammer even though jammer also present'))
                result = result.replace('m', 'j')
            elif 'j' in result:
                await self.bot.say(inline('Warning: mortals not supported by dawnglare, replaced with poison'))
                result = result.replace('m', 'p')
            else:
                await self.bot.say(inline('Warning: mortals not supported by dawnglare, replaced with jammer'))
                result = result.replace('m', 'j')

        if 'u' in result:
            await self.bot.say(inline('Warning: had to replace unknowns with jammers.'))
            result = result.replace('u', 'j')
        dawnglare_url = "http://pad.dawnglare.com/?patt=" + result
        await self.bot.say(dawnglare_url)


    def classify_to_string(self, image_data):
        nparr = np.fromstring(image_data, np.uint8)
        img_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        extractor = padvision.SimilarityBoardExtractor(self.orb_type_to_images, img_np)
        board = extractor.get_board()

        return ''.join([''.join(r) for r in board])

def is_valid_image_url(url):
    return url.startswith('http') and (url.endswith('.png') or url.endswith('.jpg'))

def check_folder():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    if not os.path.exists(ORB_DATA_DIR):
        os.makedirs(ORB_DATA_DIR)

def check_file():
    pass

def setup(bot):
    check_folder()
    check_file()
    n = PadBoard(bot)
    bot.add_listener(n.log_message, "on_message")
    bot.add_cog(n)
