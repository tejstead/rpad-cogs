from collections import defaultdict
from collections import deque
from io import BytesIO
import os
from zipfile import ZipFile

import aiohttp
import cv2
import discord
from discord.ext import commands
import numpy as np

from __main__ import send_cmd_help

from . import padvision
from . import rpadutils
from .utils import checks
from .utils.chat_formatting import *


DATA_DIR = os.path.join('data', 'padboard')

DAWNGLARE_BOARD_TEMPLATE = "https://candyninja001.github.io/Puzzled/?patt={}"
MIRUGLARE_BOARD_TEMPLATE = "https://storage.googleapis.com/mirubot/websites/padsim/index.html?patt={}"


class PadBoard:
    def __init__(self, bot):
        self.bot = bot
        self.logs = defaultdict(lambda: deque(maxlen=1))

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

        img_board_nc = self.nc_classify(image_data)

        board_text_nc = ''.join([''.join(r) for r in img_board_nc])
        # Convert O (used by padvision code) to X (used by Puzzled for bombs)
        board_text_nc = board_text_nc.replace('o', 'x')
        img_url = DAWNGLARE_BOARD_TEMPLATE.format(board_text_nc)
        img_url2 = MIRUGLARE_BOARD_TEMPLATE.format(board_text_nc)

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

    def nc_classify(self, image_data):
        nparr = np.fromstring(image_data, np.uint8)
        img_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        model_path = '/home/tactical0retreat/git/pad-models/ICN3582626462823189160/model.tflite'
        img_extractor = padvision.NeuralClassifierBoardExtractor(model_path, img_np, image_data)
        return img_extractor.get_board()

def check_folder():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def check_file():
    pass


def setup(bot):
    check_folder()
    check_file()
    n = PadBoard(bot)
    bot.add_listener(n.log_message, "on_message")
    bot.add_cog(n)
