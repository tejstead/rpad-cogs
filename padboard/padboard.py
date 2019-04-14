from abc import ABCMeta, abstractmethod
from builtins import map
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
from . import rpadutils
from .utils import checks
from .utils.chat_formatting import *
from .utils.dataIO import fileIO


DATA_DIR = os.path.join('data', 'padboard')
ORB_DATA_DIR = os.path.join(DATA_DIR, 'orb_images')

DAWNGLARE_BOARD_TEMPLATE = "https://candyninja001.github.io/Puzzled/?patt={}"
MIRUGLARE_BOARD_TEMPLATE = "https://storage.googleapis.com/mirubot/websites/padsim/index.html?patt={}"


class PadBoard:
    def __init__(self, bot):
        self.bot = bot
        self.logs = defaultdict(lambda: deque(maxlen=1))
        self.orb_type_to_images = padvision.load_orb_images_dir_to_map(ORB_DATA_DIR)

    async def log_message(self, message):
        url = rpadutils.extract_image_url(message)
        if url:
            self.logs[message.author.id].append(url)

    @commands.group(pass_context=True)
    @checks.is_owner()
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

            await self.bot.say(box('deleting existing files and unzipping files: {}'.format(len(files))))
            self.clear_training_folder()
            zip_file.extractall(ORB_DATA_DIR)
            await self.bot.say(inline('done extracting'))
            self.orb_type_to_images = padvision.load_orb_images_dir_to_map(ORB_DATA_DIR)
            await self.bot.say(inline('done reloading'))

    def find_image(self, user_id):
        urls = list(self.logs[user_id])
        if urls:
            return urls[-1]
        return None

    async def download_image(self, image_url):
        async with aiohttp.get(image_url) as r:
            if r.status == 200:
                image_data = await r.read()
                return image_data
        return None

    @commands.command(pass_context=True)
    async def dawnglare(self, ctx, user: discord.Member=None):
        """Converts your most recent image to a dawnglare link

        Scans your recent messages for images (links with embeds, or uploads)
        and attempts to detect a board, and the orbs in that board. Posts a
        link to dawnglare with the contents of your board.
        """
        image_data = await self.get_recent_image(ctx, user, ctx.message)
        if not image_data:
            return

        img_board = self.classify(image_data)

        board_text = ''.join([''.join(r) for r in img_board])
        # Convert O (used by padvision code) to X (used by Puzzled for bombs)
        board_text = board_text.replace('o', 'x')
        img_url = DAWNGLARE_BOARD_TEMPLATE.format(board_text)
        img_url2 = MIRUGLARE_BOARD_TEMPLATE.format(board_text)

        msg = '{}\n{}'.format(img_url, img_url2)
        await self.bot.say(msg)

    async def get_recent_image(self, ctx, user: discord.Member=None, message: discord.Message=None):
        user_id = user.id if user else ctx.message.author.id

        image_url = rpadutils.extract_image_url(message)
        if image_url is None:
            image_url = self.find_image(user_id)

        if not image_url:
            if user:
                await self.bot.say(inline("Couldn't find an image in that user's recent messages."))
            else:
                await self.bot.say(inline("Couldn't find an image in your recent messages. Upload or link to one and try again"))
            return None

        image_data = await self.download_image(image_url)
        if not image_data:
            await self.bot.say(inline("failed to download"))
            return None

        return image_data

    def classify(self, image_data):
        nparr = np.fromstring(image_data, np.uint8)
        img_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        img_extractor = padvision.SimilarityBoardExtractor(self.orb_type_to_images, img_np)
        img_board = img_extractor.get_board()
        return img_board


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
