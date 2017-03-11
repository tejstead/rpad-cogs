from collections import defaultdict
import os

import cv2
import np


class PadVision:
    def __init__(self, bot):
        self.bot = bot

def setup(bot):
    n = PadVision(bot)
    bot.add_cog(n)


###############################################################################
# Library code
###############################################################################

EXTRACTABLE = 'rbgldhjpm'

# returns y, x
def board_iterator():
    for y in range(5):
        for x in range(6):
            yield y, x


def dbg_display(img):
    cv2.namedWindow('image', cv2.WINDOW_NORMAL)
    cv2.imshow('image', img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

# Compare two images by getting the L2 error (square-root of sum of squared error).
def getL2Err(A, B):
    # Calculate the L2 relative error between images.
    errorL2 = cv2.norm(A, B, cv2.NORM_L2);
    # Convert to a reasonable scale, since L2 error is summed across all pixels of the image.
    return errorL2 / (100 * 100);

def getMSErr(imageA, imageB):
    # the 'Mean Squared Error' between the two images is the
    # sum of the squared difference between the two images;
    # NOTE: the two images must have the same dimension
    err = np.sum((imageA.astype("float") - imageB.astype("float")) ** 2)
    err /= float(imageA.shape[0] * imageA.shape[1])

    # return the MSE, the lower the error, the more "similar"
    # the two images are
    return err

def resizeOrbImg(img):
    height, width, _ = img.shape
    if height < 100 or width < 100:
        return cv2.resize(img, (100, 100), interpolation=cv2.INTER_CUBIC)
    elif height > 100 or width > 100:
        return cv2.resize(img, (100, 100), interpolation=cv2.INTER_AREA)
    else:
        return img

def find_best_match(orb_img, orb_type_to_images, similarity_fn):
    best_match = 'u'
    best_match_sim = 99999
    for orb_type, image_list in orb_type_to_images.items():
        for i in image_list:
            sim = similarity_fn(orb_img, i)
            if sim < best_match_sim:
                best_match = orb_type
                best_match_sim = sim
    return best_match, best_match_sim

def load_orb_images_dir_to_map(orb_image_dir):
    orb_type_to_images = defaultdict(list)

    for f in os.listdir(orb_image_dir):
        img = cv2.imread('{}/{}'.format(orb_image_dir, f), cv2.IMREAD_COLOR)
        img = resizeOrbImg(img)
        orb_type = f[0]
        orb_type_to_images[orb_type].append(img)

    return orb_type_to_images

class OrbExtractor(object):
    def __init__(self, img):
        self.img = img

        height, width, _ = img.shape

        # Detect left/right border size
        xstart = 0
        while True:
            low = int(height * 2 / 3)
            # board starts in the lower half, and has slightly deeper indentation
            # than the monster display
            if max(img[low, xstart]) > 0:
                break
            xstart += 1

        # compute true baseline from the bottom (removes android buttons)
        yend = height - 1
        while True:
            if max(img[yend, xstart + 10]) > 0:
                break
            yend -= 1

        # compute true board size
        board_width = width - (xstart * 2)
        orb_size = int(board_width / 6)

        ystart = yend - orb_size * 5

        self.xstart = xstart
        self.ystart = ystart
        self.orb_size = orb_size

    def markup_orbs(self):
        for y in range(5):
            for x in range(6):
                box_xstart, box_ystart, box_xend, box_yend = self.get_orb_vertices(x, y)
                cv2.rectangle(self.img, (box_xstart, box_ystart), (box_xend, box_yend), (0, 255, 0), 1)
        cv2.namedWindow('image', cv2.WINDOW_NORMAL)
        cv2.imshow('image', self.img)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    def get_orb_vertices(self, x, y):
        # Consider adding an offset here Sto get rid of padding?
        offset = 0
        box_ystart = y * self.orb_size + self.ystart
        box_yend = box_ystart + self.orb_size
        box_xstart = x * self.orb_size + self.xstart
        box_xend = box_xstart + self.orb_size
        return box_xstart + offset, box_ystart + offset, box_xend - offset, box_yend - offset

    def get_orb_coords(self, x, y):
        box_xstart, box_ystart, box_xend, box_yend = self.get_orb_vertices(x, y)
        coords = (slice(box_ystart, box_yend),
                slice(box_xstart, box_xend),
                slice(None))
        return coords

    def get_orb_img(self, x, y):
        return self.img[self.get_orb_coords(x, y)]


class SimilarityBoardExtractor(object):
    def __init__(self, orb_type_to_images, img):
        self.orb_type_to_images = orb_type_to_images
        self.img = img

    def get_board(self):
        oe = OrbExtractor(self.img)

        results = [['u' for x in range(6)] for y in range(5)]
        for y, x in board_iterator():
            orb_img = oe.get_orb_img(x, y)
            orb_img = resizeOrbImg(orb_img)

            best_match, best_match_sim = find_best_match(orb_img, self.orb_type_to_images, getMSErr)
            results[y][x] = best_match

        return results

