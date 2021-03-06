#!/usr/bin/env python

# wujian@2019

import argparse

import numpy as np

from libs.ssl import ml_ssl

from libs.data_handler import SpectrogramReader, NumpyReader
from libs.utils import get_logger, EPSILON
from libs.opts import StftParser

logger = get_logger(__name__)


def add_wta(masks_list, eps=1e-4):
    """
    Produce winner-take-all masks
    """
    masks = np.stack(masks_list, axis=-1)
    max_mask = np.max(masks, -1)
    wta_masks = []
    for spk_mask in masks_list:
        m = np.where(spk_mask == max_mask, spk_mask, eps)
        wta_masks.append(m)
    return wta_masks


def run(args):
    stft_kwargs = {
        "frame_len": args.frame_len,
        "frame_hop": args.frame_hop,
        "round_power_of_two": args.round_power_of_two,
        "window": args.window,
        "center": args.center,
        "transpose": True
    }
    steer_vector = np.load(args.steer_vector)
    num_doa, _, _ = steer_vector.shape
    min_doa, max_doa = list(map(float, args.doa_range.split(",")))
    if args.output == "radian":
        angles = np.linspace(min_doa * np.pi / 180, max_doa * np.pi / 180,
                             num_doa + 1)
    else:
        angles = np.linspace(min_doa, max_doa, num_doa + 1)

    spectrogram_reader = SpectrogramReader(args.wav_scp, **stft_kwargs)
    mask_reader = None
    if args.mask_scp:
        mask_reader = [NumpyReader(scp) for scp in args.mask_scp.split(",")]
    online = (args.chunk_len > 0 and args.look_back > 0)
    if online:
        logger.info("Set up in online mode: chunk_len " +
                    f"= {args.chunk_len}, look_back = {args.look_back}")

    with open(args.doa_scp, "w") as doa_out:
        for key, stft in spectrogram_reader:
            # stft: M x T x F
            _, _, F = stft.shape
            if mask_reader:
                # T x F => F x T
                mask = [r[key] for r in mask_reader] if mask_reader else None
                if args.winner_take_all >= 0 and len(mask_reader) > 1:
                    mask = add_wta(mask, eps=args.winner_take_all)
                mask = mask[0]
                # F x T => T x F
                if mask.shape[-1] != F:
                    mask = mask.transpose()
            else:
                mask = None
            if not online:
                idx = ml_ssl(stft,
                             steer_vector,
                             mask=mask,
                             compression=-1,
                             eps=EPSILON)
                doa = angles[idx]
                logger.info(f"Processing utterance {key}: {doa:.4f}")
                doa_out.write(f"{key}\t{doa:.4f}\n")
            else:
                logger.info(f"Processing utterance {key}...")
                T = stft.shape[-1]
                online_doa = []
                for t in range(0, T, args.chunk_len):
                    s = max(t - args.look_back, 0)
                    if mask is not None:
                        chunk_mask = mask[..., s:t + args.chunk_len]
                    else:
                        chunk_mask = None
                    idx = ml_ssl(stft[..., s:t + args.chunk_len],
                                 steer_vector,
                                 mask=chunk_mask,
                                 compression=-1,
                                 eps=EPSILON)
                    doa = angles[idx]
                    online_doa.append(doa)
                doa_str = " ".join([f"{d:.4f}" for d in online_doa])
                doa_out.write(f"{key}\t{doa_str}\n")
    logger.info(f"Processing {len(spectrogram_reader)} utterance done")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Command to ML-based SSL",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        parents=[StftParser.parser])
    parser.add_argument("wav_scp",
                        type=str,
                        help="Multi-channel wave rspecifier")
    parser.add_argument("steer_vector",
                        type=str,
                        help="Pre-computed steer vector in each "
                        "directions (in shape A x M x F, A: number "
                        "of DoAs, M: microphone number, F: FFT bins)")
    parser.add_argument("doa_scp",
                        type=str,
                        help="Wspecifier for estimated DoA")
    parser.add_argument("--doa-range",
                        type=str,
                        default="0,360",
                        help="DoA range")
    parser.add_argument("--mask-scp",
                        type=str,
                        default="",
                        help="Rspecifier for TF-masks in numpy format")
    parser.add_argument("--output",
                        type=str,
                        default="radian",
                        choices=["radian", "angle"],
                        help="Output type of the DoA")
    parser.add_argument("--winner-take-all",
                        type=float,
                        default=-1,
                        help="Value of winner-take-all")
    parser.add_argument("--chunk-len",
                        type=int,
                        default=-1,
                        help="Number frames per chunk "
                        "(for online setups)")
    parser.add_argument("--look-back",
                        type=int,
                        default=125,
                        help="Number of frames to look back "
                        "(for online setups)")
    args = parser.parse_args()
    run(args)