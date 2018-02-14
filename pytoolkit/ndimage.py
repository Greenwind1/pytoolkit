"""主にnumpy配列(rows×cols×channels(RGB))の画像処理関連。

float32でRGBで0～255として扱う。
"""
import pathlib
import typing

import cv2
import numpy as np
import scipy.stats


def load(path: typing.Union[str, pathlib.Path], grayscale=False) -> np.ndarray:
    """画像の読み込み。

    やや余計なお世話だけど今後のためにfloat32に変換して返す。
    """
    flags = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
    bgr = cv2.imread(str(path), flags)
    rgb = bgr[:, :, ::-1]
    return rgb.astype(np.float32)


def save(path: typing.Union[str, pathlib.Path], rgb: np.ndarray) -> None:
    """画像の保存。

    やや余計なお世話だけど0～255にクリッピング(飽和)してから保存。
    """
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    bgr = rgb[:, :, ::-1]
    cv2.imwrite(str(path), bgr)


def rotate(rgb: np.ndarray, degrees: float, interp='lanczos') -> np.ndarray:
    """回転。"""
    cv2_interp = {
        'nearest': cv2.INTER_NEAREST,
        'bilinear': cv2.INTER_LINEAR,
        'bicubic': cv2.INTER_CUBIC,
        'lanczos': cv2.INTER_LANCZOS4,
    }[interp]
    size = (rgb.shape[1], rgb.shape[0])
    center = (size[0] // 2, size[1] // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center=center, angle=degrees, scale=1.0)
    rgb = cv2.warpAffine(rgb, rotation_matrix, size, flags=cv2_interp)
    return rgb


def pad(rgb: np.ndarray, width: int, height: int, padding='same', rand=None) -> np.ndarray:
    """パディング。width/heightはpadding後のサイズ。(左右/上下均等、端数は右と下につける)"""
    assert width >= 0
    assert height >= 0
    x1 = max(0, (width - rgb.shape[1]) // 2)
    y1 = max(0, (height - rgb.shape[0]) // 2)
    x2 = width - rgb.shape[1] - x1
    y2 = height - rgb.shape[0] - y1
    rgb = pad_ltrb(rgb, x1, y1, x2, y2, padding, rand)
    assert rgb.shape[1] == width and rgb.shape[0] == height
    return rgb


def pad_ltrb(rgb: np.ndarray, x1: int, y1: int, x2: int, y2: int, padding='same', rand=None):
    """パディング。x1/y1/x2/y2は左/上/右/下のパディング量。"""
    assert padding in ('same', 'zero', 'reflect', 'wrap', 'rand')
    if padding == 'same':
        mode = 'edge'
    elif padding == 'zero':
        mode = 'constant'
    elif padding == 'rand':
        assert rand is not None
        mode = 'constant'
    else:
        mode = padding

    rgb = np.pad(rgb, ((y1, y2), (x1, x2), (0, 0)), mode=mode)

    if padding == 'rand':
        if y1:
            rgb[:+y1, :, :] = rand.randint(0, 255, size=(y1, rgb.shape[1], rgb.shape[2]))
        if y2:
            rgb[-y2:, :, :] = rand.randint(0, 255, size=(y2, rgb.shape[1], rgb.shape[2]))
        if x1:
            rgb[:, :+x1, :] = rand.randint(0, 255, size=(rgb.shape[0], x1, rgb.shape[2]))
        if x2:
            rgb[:, -x2:, :] = rand.randint(0, 255, size=(rgb.shape[0], x2, rgb.shape[2]))

    return rgb


def crop(rgb: np.ndarray, x: int, y: int, width: int, height: int) -> np.ndarray:
    """切り抜き。"""
    assert 0 <= x < rgb.shape[1]
    assert 0 <= y < rgb.shape[0]
    assert width >= 0
    assert height >= 0
    assert 0 <= x + width <= rgb.shape[1]
    assert 0 <= y + height <= rgb.shape[0]
    return rgb[y:y + height, x:x + width, :]


def flip_lr(rgb: np.ndarray) -> np.ndarray:
    """左右反転。"""
    return rgb[:, ::-1, :]


def flip_tb(rgb: np.ndarray) -> np.ndarray:
    """上下反転。"""
    return rgb[::-1, :, :]


def resize(rgb: np.ndarray, width: int, height: int, padding=None, interp='lanczos') -> np.ndarray:
    """リサイズ。"""
    assert interp in ('nearest', 'bilinear', 'bicubic', 'lanczos')
    if rgb.shape[1] == width and rgb.shape[0] == height:
        return rgb
    # パディングしつつリサイズ (縦横比維持)
    if padding is not None:
        assert padding in ('same', 'zero')
        resize_rate_w = width / rgb.shape[1]
        resize_rate_h = height / rgb.shape[0]
        resize_rate = min(resize_rate_w, resize_rate_h)
        resized_w = int(rgb.shape[0] * resize_rate)
        resized_h = int(rgb.shape[1] * resize_rate)
        if rgb.shape[1] != resized_w or rgb.shape[0] != resized_h:
            rgb = resize(rgb, resized_w, resized_h, padding=None, interp=interp)
        return pad(rgb, width, height)
    # パディングせずリサイズ (縦横比無視)
    if rgb.shape[1] < width and rgb.shape[0] < height:  # 拡大
        cv2_interp = {
            'nearest': cv2.INTER_NEAREST,
            'bilinear': cv2.INTER_LINEAR,
            'bicubic': cv2.INTER_CUBIC,
            'lanczos': cv2.INTER_LANCZOS4,
        }[interp]
    else:  # 縮小
        cv2_interp = cv2.INTER_NEAREST if interp == 'nearest' else cv2.INTER_AREA
    rgb = cv2.resize(rgb, (width, height), interpolation=cv2_interp)
    return rgb


def gaussian_noise(rgb: np.ndarray, rand: np.random.RandomState, scale: float) -> np.ndarray:
    """ガウシアンノイズ。scaleは0～50くらい。小さいほうが色が壊れないかも。"""
    return rgb + rand.normal(0, scale, size=rgb.shape).astype(rgb.dtype)


def blur(rgb: np.ndarray, sigma: float) -> np.ndarray:
    """ぼかし。sigmaは0～1程度がよい？"""
    rgb = cv2.GaussianBlur(rgb, (5, 5), sigma)
    return rgb


def unsharp_mask(rgb: np.ndarray, sigma: float, alpha=2.0) -> np.ndarray:
    """シャープ化。sigmaは0～1程度、alphaは1～2程度がよい？"""
    blured = blur(rgb, sigma)
    return rgb + (rgb - blured) * alpha


def median(rgb: np.ndarray, size: int) -> np.ndarray:
    """メディアンフィルタ。sizeは3程度がよい？"""
    rgb = cv2.medianBlur(rgb, size)
    return rgb


def brightness(rgb: np.ndarray, beta: float) -> np.ndarray:
    """明度の変更。betaの例：`np.random.uniform(-32, +32)`"""
    rgb += beta
    return rgb


def contrast(rgb: np.ndarray, alpha: float) -> np.ndarray:
    """コントラストの変更。alphaの例：`np.random.uniform(0.75, 1.25)`"""
    rgb *= alpha
    return rgb


def saturation(rgb: np.ndarray, alpha: float) -> np.ndarray:
    """彩度の変更。alphaの例：`np.random.uniform(0.5, 1.5)`"""
    gs = to_grayscale(rgb)
    rgb *= alpha
    rgb += (1 - alpha) * gs[:, :, np.newaxis]
    return rgb


def hue_lite(rgb: np.ndarray, alpha: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """色相の変更の適当バージョン。"""
    assert alpha.shape == (3,)
    assert beta.shape == (3,)
    assert (alpha > 0).all()
    rgb *= alpha / scipy.stats.hmean(alpha)
    rgb += beta - np.mean(beta)
    return rgb


def to_grayscale(rgb: np.ndarray) -> np.ndarray:
    """グレースケール化。"""
    return rgb.dot([0.299, 0.587, 0.114])
