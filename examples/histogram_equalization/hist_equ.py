"""Example of adaptative histogram equalization."""
from typing import List, Optional, Tuple, cast
import math
import time

from matplotlib import pyplot as plt
import cv2
import numpy as np
import torch
import torch.nn.functional as F

import kornia
from kornia.utils import image


def plot_hist(lightness: torch.Tensor, title: Optional[str] = None) -> None:
    """Plot the histogram and the normalized cum histogram.

    Args:
      lightness (torch.Tensor): gray scale image (BxHxW)
      title (str, optional): title to be shown. Default: None

    """
    if lightness.dim() == 2:
        lightness = lightness[None]
    B = lightness.shape[0]
    vec: np.ndarray = lightness.mul(255).view(B, -1).cpu().numpy()

    fig, ax1 = plt.subplots(ncols=B)
    if title is not None:
        fig.suptitle(title, fontsize=16, y=1.)
    ax = ax1
    for i in range(B):
        if B > 1:
            ax = ax1[i]
        color = "tab:blue"
        ax.set_xlabel("Intensity")
        ax.set_ylabel("Histogram", color=color)
        ax.tick_params(axis="y", labelcolor=color)
        ax.hist(vec[i], range=(0, 255), bins=256, color=color)
        ax2 = ax.twinx()
        color = "tab:red"
        ax2.set_ylabel("Normalized Cumulative Histogram", color=color)  # we already handled the x-label with ax1
        ax2.tick_params(axis="y", labelcolor=color)
        ax2.hist(vec[i], histtype="step", range=(0, 255), bins=256, cumulative=True, density=True, color=color)
    plt.tight_layout()
    plt.show()


def plot_image(img_rgb: torch.Tensor, lightness: Optional[torch.Tensor] = None) -> None:
    """Plot image changing the intensity.

    Args:
        img_rgb (torch.Tensor): original image (3xHxW) [0..1]
        lightness (torch.Tensor): normalized [0..1] intensity to be applied to each pixel (1xHxW).

    """
    img = img_rgb
    if img.dim() == 3:
        img = img[None]
    if lightness is not None:
        img_lab: torch.Tensor = kornia.rgb_to_lab(img)
        img_lab[..., 0, :, :] = lightness.mul(100).squeeze(-3)
        img = kornia.lab_to_rgb(img_lab)

    fig, ax = plt.subplots(ncols=img.shape[0])
    ax1 = ax
    for i in range(img.shape[0]):
        if img.shape[0] > 1:
            ax1 = ax[i]
        ax1.imshow(kornia.tensor_to_image(img[i].mul(255).clamp(0, 255).int()), cmap="gray")
        ax1.axis("off")
    plt.show()


def plot_hsv(img_hsv: torch.Tensor) -> None:
    """Plot image changing the intensity.

    Args:
        img_hsv (torch.Tensor): original image (WxHx3) [0..1]

    """
    img_rgb: torch.Tensor = kornia.hsv_to_rgb(img_hsv)
    plt.imshow(kornia.tensor_to_image(img_rgb.mul(255).clamp(0, 255).int()))
    plt.axis("off")


def visualize(tiles: torch.Tensor) -> None:
    """Show tiles as tiles.

    Args:
        tiles (torch.Tensor): set of tiles to be displayed (GH, GW, C, TH, TW)

    """
    fig = plt.figure(figsize=(tiles.shape[1], tiles.shape[0]))
    for i in range(tiles.shape[0]):
        for j in range(tiles.shape[1]):
            inp = kornia.tensor_to_image(tiles[i][j])
            inp = np.array(inp)

            ax = fig.add_subplot(
                tiles.shape[0], tiles.shape[1], ((i * tiles.shape[1]) + j) + 1, xticks=[], yticks=[])
            plt.imshow(inp)
    plt.show()


def load_test_images(device: torch.device) -> torch.Tensor:
    """Load test images."""
    # load using opencv and convert to RGB
    list_img_rgb: List[torch.Tensor] = []
    img_bgr: np.ndarray = cv2.imread(
        "/Users/luis/Projects/kornia/examples/histogram_equalization/img1.png", cv2.IMREAD_COLOR)
    list_img_rgb.append(
        kornia.image_to_tensor(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)).to(dtype=torch.float32, device=device).div(255)
    )

    img_bgr = cv2.imread(
        "/Users/luis/Projects/kornia/examples/histogram_equalization/img2.jpg", cv2.IMREAD_COLOR)
    list_img_rgb.append(
        kornia.image_to_tensor(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)).to(dtype=torch.float32, device=device).div(255)
    )
    size: Tuple[int, int] = cast(Tuple[int, int], tuple([*list_img_rgb[0].shape[1:]]))
    list_img_rgb[1] = kornia.center_crop(list_img_rgb[1][None], size).squeeze()
    img_rgb: torch.Tensor = torch.stack(list_img_rgb)
    return img_rgb


def compute_tiles(imgs: torch.Tensor, grid_size: Tuple[int, int], even_tile_size: bool = False
                  ) -> Tuple[torch.Tensor, torch.Tensor]:
    """Compute tiles on an image according to a grid size.

    Note that padding can be added to the image in order to crop properly the image.
    So, the grid_size (GH, GW) x tile_size (TH, TW) >= image_size (H, W)

    Args:
        imgs (torch.Tensor): batch of 2D images with shape (B, C, H, W) or (C, H, W).
        grid_size (Tuple[int, int]): number of tiles to be cropped in each direction (GH, GW)
        even_tile_size (bool, optional): Determine if the width and height of the tiles must be even. Default: False.

    Returns:
        torch.Tensor: tensor with tiles (B, GH, GW, C, TH, TW). B = 1 in case of a single image is provided.
        torch.Tensor: tensor with the padded batch of 2D imageswith shape (B, C, H', W')

    """
    batch: torch.Tensor = image._to_bchw(imgs)  # B x C x H x W

    # compute stride and kernel size
    h, w = batch.shape[-2:]
    kernel_vert = math.ceil(h / grid_size[0])
    kernel_horz = math.ceil(w / grid_size[1])

    if even_tile_size:
        kernel_vert += 1 if kernel_vert % 2 else 0
        kernel_horz += 1 if kernel_horz % 2 else 0

    # add padding (with that kernel size we could need some extra cols and rows...)
    pad_vert = kernel_vert * grid_size[0] - h
    pad_horz = kernel_horz * grid_size[1] - w
    # add the padding in the last coluns and rows
    if pad_vert > 0 or pad_horz > 0:
        batch = F.pad(batch, [0, pad_horz, 0, pad_vert], mode='reflect')  # B x C x H' x W'

    # compute tiles
    c: int = batch.shape[-3]
    tiles: torch.Tensor = (batch.unfold(1, c, c)  # unfold(dimension, size, step)
                                .unfold(2, kernel_vert, kernel_vert)
                                .unfold(3, kernel_horz, kernel_horz)
                                .squeeze(1))  # GH x GW x C x TH x TW
    assert tiles.shape[-5] == grid_size[0]  # check the grid size
    assert tiles.shape[-4] == grid_size[1]
    return tiles, batch


def compute_interpolation_tiles(padded_imgs: torch.Tensor, tile_size: Tuple[int, int]) -> torch.Tensor:
    """Compute interpolation tiles on a properly padded set of images.

    Note that images must be padded. So, the tile_size (TH, TW) * grid_size (GH, GW) = image_size (H, W)

    Args:
        padded_imgs (torch.Tensor): batch of 2D images with shape (B, C, H, W) already padded to extract tiles
                                    of size (TH, TW).
        tile_size (Tuple[int, int]): shape of the current tiles (TH, TW).

    Returns:
        torch.Tensor: tensor with the interpolation tiles (B, 2GH, 2GW, C, TH/2, TW/2).

    """
    assert padded_imgs.dim() == 4, "Images Tensor must be 4D."
    assert padded_imgs.shape[-2] % tile_size[0] == 0, "Images are not correctly padded."
    assert padded_imgs.shape[-1] % tile_size[1] == 0, "Images are not correctly padded."

    # tiles to be interpolated are built by dividing in 4 each alrady existing
    interp_kernel_vert = tile_size[0] // 2
    interp_kernel_horz = tile_size[1] // 2

    c: int = padded_imgs.shape[-3]
    interp_tiles: torch.Tensor = (padded_imgs.unfold(1, c, c)
                                             .unfold(2, interp_kernel_vert, interp_kernel_vert)
                                             .unfold(3, interp_kernel_horz, interp_kernel_horz)
                                             .squeeze(1))  # 2GH x 2GW x C x TH/2 x TW/2
    assert interp_tiles.shape[-3] == c
    assert interp_tiles.shape[-2] == tile_size[0] / 2
    assert interp_tiles.shape[-1] == tile_size[1] / 2
    return interp_tiles


def compute_luts(tiles_x_im: torch.Tensor) -> torch.Tensor:
    """Compute luts for a batched set of tiles.

    Args:
        tiles_x_im (torch.Tensor): set of tiles per image to apply the lut. (B, GH, GW, C, TH, TW)

    Returns:
        torch.Tensor: Lut for each tile (B, GH, GW, C, 256)

    """
    def lut(patch: torch.Tensor, diff: bool = False) -> torch.Tensor:
        # function adapted from:
        # https://github.com/python-pillow/Pillow/blob/master/src/PIL/ImageOps.py
        # and https://github.com/pytorch/vision/pull/3119/files
        # and https://github.com/pytorch/vision/issues/1049
        # NOTE: torch.histc doesn't work with batches
        histo: torch.Tensor
        if not diff:
            histo = torch.histc(patch, bins=256, min=0, max=1)
        else:
            bins: torch.Tensor = torch.linspace(0, 1, 256)
            histo = kornia.enhance.histogram(patch.flatten()[None], bins, torch.tensor(0.001)).squeeze()
            histo *= patch.shape[0] * patch.shape[1]

        nonzero_histo: torch.Tensor = histo[histo > 0.999]
        step: torch.Tensor
        if nonzero_histo.numel() > 0:
            step = (nonzero_histo.sum() - nonzero_histo[-1]) // 255
        else:
            step = torch.tensor(0, device=patch.device)
        if step == 0:
            return torch.zeros_like(histo).long()  # TODO: check the best return value for this case
        lut: torch.Tensor = (torch.cumsum(histo, 0) + (step // 2)) // step
        lut = torch.cat([torch.zeros(1, device=patch.device), lut[:-1]]).clamp(0, 255).long()
        return lut

    # precompute all the luts with 256 bins
    luts: torch.Tensor  # B x GH x GW x C x 256
    luts = torch.stack([torch.stack([torch.stack([torch.stack(
        [lut(c) for c in p]) for p in row_tiles]) for row_tiles in tiles]) for tiles in tiles_x_im])
    assert luts.shape == torch.Size([*tiles_x_im.shape[0:4]] + [256])
    return luts


def compute_luts_optim(tiles_x_im: torch.Tensor, diff: bool = False) -> torch.Tensor:
    """Compute luts for a batched set of tiles.

    Args:
        tiles_x_im (torch.Tensor): set of tiles per image to apply the lut. (B, GH, GW, C, TH, TW)

    Returns:
        torch.Tensor: Lut for each tile (B, GH, GW, C, 256)

    """
    tiles: torch.Tensor = tiles_x_im.reshape(-1, tiles_x_im.shape[-2] * tiles_x_im.shape[-1])
    pixels: int = tiles_x_im.shape[-2] * tiles_x_im.shape[-1]
    histos: torch.Tensor = torch.zeros(tiles.shape[0], 256, device=tiles.device)
    if not diff:
        for i, tile in enumerate(tiles):
            histos[i] = torch.histc(tile, bins=256, min=0, max=1)
    else:
        bins: torch.Tensor = torch.linspace(0, 1, 256)
        histos = kornia.enhance.histogram(tiles, bins, torch.tensor(0.001)).squeeze()
        histos *= pixels

    step: float = (pixels - 1) / 255
    luts: torch.Tensor = (torch.cumsum(histos, 1) + (step // 2)) // step
    luts = torch.cat([torch.zeros(luts.shape[0], 1, device=tiles_x_im.device), luts[..., :-1]], 1).clamp(0, 255)
    luts = luts.view(([*tiles_x_im.shape[0:4]] + [256]))
    return luts


def compute_equalized_tiles(interp_tiles: torch.Tensor, luts: torch.Tensor) -> torch.Tensor:
    """Equalize the tiles.

    Args:
        interp_tiles (torch.Tensor): set of interpolation tiles. (B, 2GH, 2GW, C, TH/2, TW/2)
        luts (torch.Tensor): luts for each one of the original tiles. (B, GH, GW, C, 256)

    Returns:
        torvh.Tensor: equalized tiles (B, 2GH, 2GW, C, TH/2, TW/2)

    """
    tiles_equalized: torch.Tensor = torch.zeros_like(interp_tiles, dtype=torch.long)

    num_imgs: int  # number of batched images
    gh: int  # 2x the number of tiles used to compute the histograms
    gw: int
    c: int  # number of channels
    th: int  # /2 the sizes of the tiles used to compute the histograms
    tw: int
    num_imgs, gh, gw, c, th, tw = interp_tiles.shape

    # compute the interpolation weights (shapes are 2 x TH x TW because they must be applied to 2 interp tiles)
    ih = torch.arange(2 * th - 1, -1, -1, device=interp_tiles.device).div(2 * th - 1)[None].T.expand(2 * th, tw)
    ih = ih.unfold(0, th, th).unfold(1, tw, tw).squeeze(1)  # 2 x TH x TW
    iw = torch.arange(2 * tw - 1, -1, -1, device=interp_tiles.device).div(2 * tw - 1).expand(th, 2 * tw)
    iw = iw.unfold(0, th, th).unfold(1, tw, tw).squeeze(0)  # 2 x TH x TW
    # plot_image(m[0][None])
    # plot_image(n[0][None])

    flatten_interp_tiles: torch.Tensor = (interp_tiles * 255).long().flatten(-2, -1)  # B x GH x GW x C x (THxTW)
    for im in range(num_imgs):
        for j in range(gh):
            for i in range(gw):
                # corner region
                if (i == 0 or i == gw - 1) and (j == 0 or j == gh - 1):
                    a = torch.gather(luts[im, j // 2, i // 2], 1, flatten_interp_tiles[im, j, i])
                    a = a.reshape(c, th, tw)
                    tiles_equalized[im, j, i] = a
                    # print(f'corner ({j},{i})')
                    continue

                # border region (h)
                if i == 0 or i == gw - 1:
                    t = torch.gather(luts[im, max(0, j // 2 + j % 2 - 1), i // 2],
                                     1, flatten_interp_tiles[im, j, i]).reshape(c, th, tw)
                    b = torch.gather(luts[im, j // 2 + j % 2, i // 2],
                                     1, flatten_interp_tiles[im, j, i]).reshape(c, th, tw)
                    tiles_equalized[im, j, i] = ih[(j + 1) % 2] * (t - b) + b
                    # print(f'border h ({j},{i})')
                    continue

                # border region (w)
                if j == 0 or j == gh - 1:
                    l = torch.gather(luts[im, j // 2, max(0, i // 2 + i % 2 - 1)],
                                     1, flatten_interp_tiles[im, j, i]).reshape(c, th, tw)
                    r = torch.gather(luts[im, j // 2, i // 2 + i % 2],
                                     1, flatten_interp_tiles[im, j, i]).reshape(c, th, tw)
                    tiles_equalized[im, j, i] = iw[(i + 1) % 2] * (l - r) + r
                    # print(f'border w ({j},{i})')
                    continue

                # internal region
                tl = torch.gather(luts[im, max(0, j // 2 + j % 2 - 1), max(0, i // 2 + i % 2 - 1)],
                                  1, flatten_interp_tiles[im, j, i]).reshape(c, th, tw)
                tr = torch.gather(luts[im, max(0, j // 2 + j % 2 - 1), i // 2 + i % 2],
                                  1, flatten_interp_tiles[im, j, i]).reshape(c, th, tw)
                bl = torch.gather(luts[im, j // 2 + j % 2, max(0, i // 2 + i % 2 - 1)],
                                  1, flatten_interp_tiles[im, j, i]).reshape(c, th, tw)
                br = torch.gather(luts[im, j // 2 + j % 2, i // 2 + i % 2],
                                  1, flatten_interp_tiles[im, j, i]).reshape(c, th, tw)
                t = iw[(i + 1) % 2] * (tl - tr) + tr
                b = iw[(i + 1) % 2] * (bl - br) + br
                tiles_equalized[im, j, i] = ih[(j + 1) % 2] * (t - b) + b
    return tiles_equalized


@profile
def main():
    """Run the main function."""
    on_rgb: bool = False
    if not torch.cuda.is_available():
        print("WARNING: Cuda is not enabled!!!")
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    img_rgb: torch.Tensor = load_test_images(device)  # B x C x H x W
    img: torch.Tensor = img_rgb
    if not on_rgb:
        img_lab: torch.Tensor = kornia.rgb_to_lab(img_rgb)
        img = img_lab[..., 0, :, :].unsqueeze(-3) / 100  # L in lab is in range [0, 100]
    # plot_image(img_rgb)
    gh = gw = 1
    grid_size: Tuple = (gh, gw)
    hist_tiles: torch.Tensor  # B x GH x GW x C x TH x TW
    img_padded: torch.Tensor  # B x C x H' x W'
    # the size of the tiles must be even in order to divide them into 4 tiles for the interpolation
    tic = time.time()
    hist_tiles, img_padded = compute_tiles(img, grid_size, True)
    # print(hist_tiles.shape)
    # visualize(hist_tiles[0])
    # visualize(hist_tiles[1])
    tile_size: Tuple = hist_tiles.shape[-2:]
    interp_tiles: torch.Tensor = (
        compute_interpolation_tiles(img_padded, tile_size))  # B x 2GH x 2GW x C x TH/2 x TW/2
    # print(interp_tiles.shape)
    # visualize(interp_tiles[0])
    # visualize(interp_tiles[1])
    time_tiles = time.time() - tic
    tic = time.time()
    for i in range(10):
        luts: torch.Tensor = compute_luts_optim(hist_tiles)  # B x GH x GW x C x B
        equalized_tiles: torch.Tensor = compute_equalized_tiles(interp_tiles, luts)  # B x 2GH x 2GW x C x TH/2 x TW/2

    p1 = torch.cat(equalized_tiles.unbind(2), 4)
    p2 = torch.cat(p1.unbind(1), 2)
    h, w = img_rgb.shape[-2:]
    p2 = p2[..., :h, :w]
    time_torch = time.time() - tic

#    if on_rgb:
#        plot_image(p2.div(255.))
#    else:
#        plot_image(img_rgb, p2.div(255.))
#        plot_hist(p2.div(255.))

    tic = time.time()
    for i in range(10):
        luts = compute_luts(hist_tiles)  # B x GH x GW x C x B
        equalized_tiles: torch.Tensor = compute_equalized_tiles(interp_tiles, luts)  # B x 2GH x 2GW x C x TH/2 x TW/2

    p1 = torch.cat(equalized_tiles.unbind(2), 4)
    p2 = torch.cat(p1.unbind(1), 2)
    h, w = img_rgb.shape[-2:]
    p2 = p2[..., :h, :w]
    time_kornia = time.time() - tic
#    if on_rgb:
#        plot_image(p2.div(255.))
#    else:
#        plot_image(img_rgb, p2.div(255.))
#        plot_hist(p2.div(255.))

    # hist equalization in kornia
    tic = time.time()
    for i in range(10):
        lightness_equalized = kornia.enhance.equalize(img).squeeze()
    time_kornia_he = time.time() - tic
#    plot_image(img_rgb, lightness_equalized)
#    plot_hist(lightness_equalized)

    print(f'time_tiles: \t{time_tiles:.5f}\ntorch: \t{time_torch:.5f}\nkornia: \t{time_kornia:.5f}\nkornia he: \t{time_kornia_he:.5f}')


if __name__ == "__main__":
    main()