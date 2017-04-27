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
from pazudorasolver.board import Board
from pazudorasolver.piece import Fire, Wood, Water, Dark, Light, Heart, Poison, Jammer, Unknown

from __main__ import send_cmd_help

from . import padvision
from .utils import checks
from .utils.chat_formatting import *
from .utils.dataIO import fileIO


DATA_DIR = 'data/padboard'
ORB_DATA_DIR = DATA_DIR + '/orb_images'

LOGS_PER_USER = 5

DAWNGLARE_BOARD_TEMPLATE = "https://storage.googleapis.com/mirubot/websites/padsim/index.html?patt={}"
DAWNGLARE_MOVE_TEMPLATE = "https://storage.googleapis.com/mirubot/websites/padsim/index.html?patt={}&replay={}"


class PadBoard:
    def __init__(self, bot):
        self.bot = bot
        self.logs = defaultdict(lambda: deque(maxlen=1))
        self.orb_type_to_images = padvision.load_orb_images_dir_to_map(ORB_DATA_DIR)

    async def log_message(self, message):
        url = self.get_image_url(message)
        if url:
            self.logs[message.author.id].append(url)

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
        urls = list(self.logs[user_id])
        if urls:
            return urls[-1]
        return None

    def get_image_url(self, m):
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
        image_data = await self.get_recent_image(ctx, user, ctx.message)
        if not image_data:
            return

        result = await self.get_dawnglare_pattern(image_data)
        dawnglare_url = DAWNGLARE_BOARD_TEMPLATE.format(result)
        await self.bot.say(dawnglare_url)

#     @commands.command(pass_context=True)
#     async def solve(self, ctx, user: discord.Member=None):
#         """Scans your recent messages for images. Attempts to convert the image into a dawnglare link with solution."""
#         image_data = await self.get_recent_image(ctx, user, ctx.message)
#         if not image_data:
#             return
#
#         result = await self.get_dawnglare_pattern(image_data)
#
#         mapping = {
#            'r' : Fire,
#            'g' : Wood,
#            'b' : Water,
#            'd' : Dark,
#            'l' : Light,
#            'h' : Heart,
#            'p' : Poison,
#            'j' : Jammer,
#            'm' : Poison,
#            'u' : Unknown,
#         }
#
#         orb_list = list(map(lambda x: mapping[x], list(result)))
#         num_rows = 5
#         num_cols = 6
#         board = Board(orb_list, num_rows, num_cols)
#
#         weights = {
#             Fire.symbol: 1.0,
#             Wood.symbol: 1.0,
#             Water.symbol: 1.0,
#             Dark.symbol: 1.0,
#             Light.symbol: 1.0,
#             Heart.symbol: 1.0,
#             Poison.symbol: 0.5,
#             Jammer.symbol: 0.5,
#             Unknown.symbol: 0.0
#         }
#
#         solver = TrPrunedBfs(weights, 300)
#         (score, moves, solved_board) = solver.solve(board, 30)
#
#         cur_orb = (0, 0)
#         converted_moves = list()
#         for m in moves:
#             cur_orb = (cur_orb[0] + m[0], cur_orb[1] + m[1])
#             converted_moves.append(str(cur_orb[0] * 6 + cur_orb[1]))
#
#         dawnglare_moves = '|'.join(converted_moves)
#         dawnglare_url = DAWNGLARE_MOVE_TEMPLATE.format(result, dawnglare_moves)
#         await self.bot.say(dawnglare_url)


    async def get_recent_image(self, ctx, user : discord.Member=None, message : discord.Message=None):
        user_id = user.id if user else ctx.message.author.id

        image_url = self.get_image_url(message)
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

    async def get_dawnglare_pattern(self, image_data):
        return self.classify_to_string(image_data)

    def classify_to_string(self, image_data):
        nparr = np.fromstring(image_data, np.uint8)
        img_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        extractor = padvision.SimilarityBoardExtractor(self.orb_type_to_images, img_np)
        board = extractor.get_board()

        return ''.join([''.join(r) for r in board])

def is_valid_image_url(url):
    url = url.lower()
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

# Hacky solver derived from Pruned BFS solver in https://github.com/ethanlu/pazudora-solver

class TrHeuristic(metaclass=ABCMeta):
    def __init__(self, weights):
        self._weights = weights
        self._diagonals = False
        self._history = {}

    @property
    def diagonals(self):
        return self._diagonals

    @diagonals.setter
    def diagonals(self, diagonals):
        self._diagonals = diagonals

    def _reset(self):
        self._history = {}

    def _remember(self, board, row, col):
        # Changed this!
        s = '{},row={},col={}'.format(board.hash, row, col)
        if s not in self._history:
            self._history[s] = True
            return self._history[s]
        else:
            return False

    def _score(self, board):
        """
        calculates a score for the current state of the board with given weights. optional row, column will calculate additional score based on localality
        :param board: current board
        :param weights: weights of pieces
        :param row: optional row
        :param column: optional column
        :return: score
        """
        matches = board.get_matches()
        chain_multiplier = len(matches)
        match_score = sum([self._weights[piece.symbol] * len(clusters) for piece, clusters in matches])
#         chaos_score = random.random()
        chaos_score = 0

        return (chain_multiplier * match_score + chaos_score)

    def _swaps(self, board, row, column):
        """
        list of possible swaps
        :param board: current board
        :param row: current row position
        :param column: current column position
        :param previous_move: previous move (as a delta tuple)
        :return: list of possible swaps as delta tuples relative to current row, column
        """
        # consider previous move's direction so that we don't end up going back
        # get swaps in all directions (up, down, left, right)
        directions = [(-1, 0), (0, 1), (1, 0), (0, -1)]
        if self._diagonals:
            directions += [(-1, -1), (-1, 1), (1, 1), (1, -1)]

        return [
            (delta_r, delta_c)
            for delta_r, delta_c in directions
            if 0 <= row + delta_r < board.rows and 0 <= column + delta_c < board.columns
        ]

    @abstractmethod
    def solve(self, board, depth):
        pass

class TrPrunedBfs(TrHeuristic):
    def __init__(self, weights, prune_limit):
        super(TrPrunedBfs, self).__init__(weights)
        self._prune_limit = prune_limit

    def _prune(self, solutions):
        sorted_solutions = sorted(solutions, key=lambda x: (x[0], len(x[1])), reverse=True)
        return sorted_solutions[0:self._prune_limit]

    def _step(self, solutions, depth):
        if depth == 0:
            return solutions
        else:
            next_solutions = []
            for score, moves, board, row, column in solutions:
                for delta_r, delta_c in self._swaps(board, row, column):
                    new_r = row + delta_r
                    new_c = column + delta_c
                    swapped_board = Board.copy_board(board).swap(row, column, new_r, new_c)
                    if self._remember(swapped_board, new_r, new_c):
                        # only add move to solutions if it is a board layout that has not been seen before
                        new_score = self._score(swapped_board)
                        new_moves = moves + [(delta_r, delta_c)]
                        next_solutions.append((new_score, new_moves, swapped_board, new_r, new_c))

            if next_solutions:
                final_solutions = solutions + next_solutions
                return self._step(self._prune(final_solutions), depth - 1)
            else:
                return solutions

    def solve(self, board, depth):
        solutions = []
        for r in range(board.rows):
            for c in range(board.columns):
                moves = [(r, c)]
                solutions.append((self._score(board), moves, board, r, c))

        best = self._step(solutions, depth)[0]
        best_moves = best[1]
        final_board = best[2]
        best_moves = self.fix_moves(best_moves, final_board)
        return (best[0], best_moves, best[2])

    def fix_moves(self, moves, board):
        cur_orb = (0, 0)
        for m in moves:
            cur_orb = (cur_orb[0] + m[0], cur_orb[1] + m[1])

        # cur_orb is now the final orb
        while len(moves) > 0:
            last_move = moves[-1]
            row = cur_orb[0]
            col = cur_orb[1]
            new_r = row + last_move[0] * -1
            new_c = col + last_move[1] * -1

            swapped_board = Board.copy_board(board).swap(row, col, new_r, new_c)
            import math
            if not math.isclose(self._score(board), self._score(swapped_board), rel_tol=.01):
                return moves

            cur_orb = (new_r, new_c)
            moves = moves[:-1]

        return moves
