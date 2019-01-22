"""主にnumpy配列(rows×cols×channels(RGB))の画像処理関連。

uint8のRGBで0～255として扱うのを前提とする。
あとグレースケールの場合もrows×cols×1の配列で扱う。
"""
import atexit
import functools
import io
import pathlib
import shutil
import tempfile
import typing

import numpy as np
import scipy.stats

from . import log, utils

_LOAD_CACHE = None
_DISKCACHE_LOAD_FAILED = False


def _clear_cache(dc):
    """キャッシュのクリア。"""
    cache_dir = dc.directory
    dc.close()
    shutil.rmtree(cache_dir, ignore_errors=True)


def _float_to_uint8(func):
    """floatからnp.uint8への変換。"""
    @functools.wraps(func)
    def _decorated(*args, **kwargs):
        return np.clip(func(*args, **kwargs), 0, 255).astype(np.uint8)
    return _decorated


def load(path_or_array: typing.Union[np.ndarray, io.IOBase, str, pathlib.Path], grayscale=False, use_cache=False, max_size=None) -> np.ndarray:
    """画像の読み込み。

    Args:
        path_or_array: 画像ファイルへのパス or npy/npzファイルへのパス or ndarray
        grascale: Trueならグレースケールで読み込み、FalseならRGB
        use_cache: 読み込み結果をdiskcacheライブラリでキャッシュするならTrue
        max_size: このサイズを超えるなら縮小する。int or tuple。tupleは(height, width)

    Returns:
        読み込み結果のndarray。

    """
    max_size = utils.normalize_tuple(max_size, 2)

    def _load():
        img = _load_impl(path_or_array, grayscale=grayscale)
        if max_size is not None and (img.shape[0] > max_size[0] or img.shape[1] > max_size[1]):
            r0 = max_size[0] / img.shape[0]
            r1 = max_size[1] / img.shape[1]
            r = min(r0, r1)
            img = resize(img, int(round(img.shape[1] * r)), int(round(img.shape[0] * r)))
        return img

    if use_cache and isinstance(path_or_array, (str, pathlib.Path)):
        global _LOAD_CACHE
        global _DISKCACHE_LOAD_FAILED
        if _LOAD_CACHE is None and not _DISKCACHE_LOAD_FAILED:
            temp_dir = tempfile.mkdtemp(suffix='pytoolkit')
            try:
                import diskcache
                _LOAD_CACHE = diskcache.Cache(temp_dir)
                atexit.register(_clear_cache, _LOAD_CACHE)
            except BaseException:
                pathlib.Path(temp_dir).rmdir()
                _DISKCACHE_LOAD_FAILED = True
                logger = log.get(__name__)
                logger.warning('diskcache load failed.', exc_info=True)
        if _LOAD_CACHE is not None:
            key = f'{path_or_array}::{max_size}'
            img = _LOAD_CACHE.get(key)
            if img is None:
                img = _load()
                _LOAD_CACHE.set(key, img)
            return img

    return _load()


def _load_impl(path_or_array: typing.Union[np.ndarray, io.IOBase, str, pathlib.Path], grayscale=False) -> np.ndarray:
    """画像の読み込みの実装。"""
    assert path_or_array is not None

    if isinstance(path_or_array, np.ndarray):
        # ndarrayならそのまま画像扱い
        img = np.copy(path_or_array)  # 念のためコピー
        assert img.dtype == np.uint8, f'ndarray dtype error: {img.dtype}'
    else:
        suffix = pathlib.Path(path_or_array).suffix.lower() if isinstance(path_or_array, (str, pathlib.Path)) else None
        if suffix in ('.npy', '.npz'):
            # .npyなら読み込んでそのまま画像扱い
            img = np.load(str(path_or_array))
            if isinstance(img, np.lib.npyio.NpzFile):
                if len(img.files) != 1:
                    raise ValueError(f'Image load failed: "{path_or_array}"" has multiple keys. ({img.files})')
                img = img[img.files[0]]
            assert img.dtype == np.uint8, f'{suffix} dtype error: {img.dtype}'
        else:
            # PILで読み込む
            import PIL.Image
            with PIL.Image.open(path_or_array) as pil_img:
                target_mode = 'L' if grayscale else 'RGB'
                if pil_img.mode != target_mode:
                    pil_img = pil_img.convert(target_mode)
                img = np.asarray(pil_img, dtype=np.uint8)

    if img is None:
        raise ValueError(f'Image load failed: {path_or_array}')
    if len(img.shape) == 2:
        img = np.expand_dims(img, axis=-1)
    if len(img.shape) != 3:
        raise ValueError(f'Image load failed: shape={path_or_array}')

    return img


def save(path: typing.Union[str, pathlib.Path], img: np.ndarray):
    """画像の保存。

    やや余計なお世話だけど0～255にクリッピング(飽和)してから保存。
    """
    assert len(img.shape) == 3
    path = pathlib.Path(path)
    img = np.clip(img, 0, 255).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == '.npy':
        np.save(str(path), img)
    elif suffix == '.npz':
        np.savez_compressed(str(path), img)
    else:
        assert img.shape[-1] in (1, 3, 4)
        import PIL.Image
        if img.shape[-1] == 1:
            pil_img = PIL.Image.fromarray(np.squeeze(img, axis=-1), 'L')
        elif img.shape[2] == 3:
            pil_img = PIL.Image.fromarray(img, 'RGB')
        elif img.shape[2] == 4:
            pil_img = PIL.Image.fromarray(img, 'RGBA')
        else:
            raise RuntimeError(f'Unknown format: shape={img.shape}')
        pil_img.save(path)


def rotate(rgb: np.ndarray, degrees: float, expand=True, interp='lanczos', border_mode='edge') -> np.ndarray:
    """回転。"""
    import cv2
    cv2_interp = {
        'nearest': cv2.INTER_NEAREST,
        'bilinear': cv2.INTER_LINEAR,
        'bicubic': cv2.INTER_CUBIC,
        'lanczos': cv2.INTER_LANCZOS4,
    }[interp]
    cv2_border = {
        'edge': cv2.BORDER_REPLICATE,
        'reflect': cv2.BORDER_REFLECT_101,
        'wrap': cv2.BORDER_WRAP,
    }[border_mode]
    size = (rgb.shape[1], rgb.shape[0])
    center = (size[0] // 2, size[1] // 2)
    m = cv2.getRotationMatrix2D(center=center, angle=degrees, scale=1.0)
    if expand:
        cos = np.abs(m[0, 0])
        sin = np.abs(m[0, 1])
        ex_w = int(np.ceil(size[1] * sin + size[0] * cos))
        ex_h = int(np.ceil(size[1] * cos + size[0] * sin))
        m[0, 2] += (ex_w / 2) - center[0]
        m[1, 2] += (ex_h / 2) - center[1]
        size = (ex_w, ex_h)
    if rgb.shape[-1] in (1, 3):
        rgb = cv2.warpAffine(rgb, m, size, flags=cv2_interp, borderMode=cv2_border)
    else:
        rotated_list = [cv2.warpAffine(rgb[:, :, ch], m, size, flags=cv2_interp, borderMode=cv2_border) for ch in range(rgb.shape[-1])]
        rgb = np.transpose(rotated_list, (1, 2, 0))
    if len(rgb.shape) == 2:
        rgb = np.expand_dims(rgb, axis=-1)
    return rgb


def pad(rgb: np.ndarray, width: int, height: int, padding='edge') -> np.ndarray:
    """パディング。width/heightはpadding後のサイズ。(左右/上下均等、端数は右と下につける)"""
    assert width >= 0
    assert height >= 0
    x1 = max(0, (width - rgb.shape[1]) // 2)
    y1 = max(0, (height - rgb.shape[0]) // 2)
    x2 = width - rgb.shape[1] - x1
    y2 = height - rgb.shape[0] - y1
    rgb = pad_ltrb(rgb, x1, y1, x2, y2, padding)
    assert rgb.shape[1] == width and rgb.shape[0] == height
    return rgb


def pad_ltrb(rgb: np.ndarray, x1: int, y1: int, x2: int, y2: int, padding='edge'):
    """パディング。x1/y1/x2/y2は左/上/右/下のパディング量。"""
    assert x1 >= 0 and y1 >= 0 and x2 >= 0 and y2 >= 0
    assert padding in ('edge', 'zero', 'half', 'one', 'reflect', 'wrap', 'mean')
    kwargs = {}
    if padding == 'zero':
        mode = 'constant'
    elif padding == 'half':
        mode = 'constant'
        kwargs['constant_values'] = (np.uint8(127),)
    elif padding == 'one':
        mode = 'constant'
        kwargs['constant_values'] = (np.uint8(255),)
    elif padding == 'mean':
        mode = 'constant'
        kwargs['constant_values'] = (np.uint8(rgb.mean()),)
    else:
        mode = padding

    rgb = np.pad(rgb, ((y1, y2), (x1, x2), (0, 0)), mode=mode, **kwargs)
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


def resize_long_side(rgb: np.ndarray, long_side: int, expand=True, interp='lanczos') -> np.ndarray:
    """長辺の長さを指定したアスペクト比維持のリサイズ。"""
    height, width = rgb.shape[:2]
    if not expand and max(width, height) <= long_side:
        return rgb
    if width >= height:  # 横長
        return resize(rgb, long_side, height * long_side // width, interp=interp)
    else:  # 縦長
        return resize(rgb, width * long_side // height, long_side, interp=interp)


def resize(rgb: np.ndarray, width: int, height: int, padding=None, interp='lanczos') -> np.ndarray:
    """リサイズ。"""
    import cv2
    assert interp in ('nearest', 'bilinear', 'bicubic', 'lanczos')
    if rgb.shape[1] == width and rgb.shape[0] == height:
        return rgb
    # パディングしつつリサイズ (縦横比維持)
    if padding is not None:
        resize_rate_w = width / rgb.shape[1]
        resize_rate_h = height / rgb.shape[0]
        resize_rate = min(resize_rate_w, resize_rate_h)
        resized_w = int(rgb.shape[0] * resize_rate)
        resized_h = int(rgb.shape[1] * resize_rate)
        rgb = resize(rgb, resized_w, resized_h, padding=None, interp=interp)
        return pad(rgb, width, height, padding=padding)
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
    if rgb.shape[-1] in (1, 3):
        rgb = cv2.resize(rgb, (width, height), interpolation=cv2_interp)
        if len(rgb.shape) == 2:
            rgb = np.expand_dims(rgb, axis=-1)
    else:
        resized_list = [cv2.resize(rgb[:, :, ch], (width, height), interpolation=cv2_interp) for ch in range(rgb.shape[-1])]
        rgb = np.transpose(resized_list, (1, 2, 0))
    return rgb


@_float_to_uint8
def gaussian_noise(rgb: np.ndarray, rand: np.random.RandomState, scale: float) -> np.ndarray:
    """ガウシアンノイズ。scaleは0～50くらい。小さいほうが色が壊れないかも。"""
    return rgb + rand.normal(0, scale, size=rgb.shape).astype(np.float32)


def blur(rgb: np.ndarray, sigma: float) -> np.ndarray:
    """ぼかし。sigmaは0～1程度がよい？"""
    import cv2
    rgb = cv2.GaussianBlur(rgb, (5, 5), sigma)
    if len(rgb.shape) == 2:
        rgb = np.expand_dims(rgb, axis=-1)
    return rgb


@_float_to_uint8
def unsharp_mask(rgb: np.ndarray, sigma: float, alpha=2.0) -> np.ndarray:
    """シャープ化。sigmaは0～1程度、alphaは1～2程度がよい？"""
    blured = blur(rgb, sigma)
    return rgb + (rgb.astype(np.float) - blured) * alpha


def median(rgb: np.ndarray, size: int) -> np.ndarray:
    """メディアンフィルタ。sizeは3程度がよい？"""
    import cv2
    rgb = cv2.medianBlur(rgb, size)
    if len(rgb.shape) == 2:
        rgb = np.expand_dims(rgb, axis=-1)
    return rgb


@_float_to_uint8
def brightness(rgb: np.ndarray, beta: float) -> np.ndarray:
    """明度の変更。betaの例：np.random.uniform(-32, +32)"""
    return rgb + np.float32(beta)


@_float_to_uint8
def contrast(rgb: np.ndarray, alpha: float) -> np.ndarray:
    """コントラストの変更。alphaの例：np.random.uniform(0.75, 1.25)"""
    return rgb * alpha


@_float_to_uint8
def saturation(rgb: np.ndarray, alpha: float) -> np.ndarray:
    """彩度の変更。alphaの例：np.random.uniform(0.5, 1.5)"""
    gs = to_grayscale(rgb)
    return alpha * rgb + (1 - alpha) * np.expand_dims(gs, axis=-1)


@_float_to_uint8
def hue_lite(rgb: np.ndarray, alpha: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """色相の変更の適当バージョン。"""
    assert alpha.shape == (3,)
    assert beta.shape == (3,)
    assert (alpha > 0).all()
    return rgb * (alpha / scipy.stats.hmean(alpha, dtype=np.float32)) + (beta - np.mean(beta, dtype=np.float32))


def to_grayscale(rgb: np.ndarray) -> np.ndarray:
    """グレースケール化。"""
    return rgb.dot(np.array([0.299, 0.587, 0.114], dtype=np.float32))


@_float_to_uint8
def standardize(rgb: np.ndarray) -> np.ndarray:
    """標準化。0～255に適当に収める。"""
    rgb = (rgb - np.mean(rgb, dtype=np.float32)) / (np.std(rgb, dtype=np.float32) + 1e-5)
    rgb = rgb * 64 + 127
    return rgb


def binarize(rgb: np.ndarray, threshold) -> np.ndarray:
    """二値化(白黒化)。"""
    assert 0 < threshold < 255
    return np.where(rgb >= threshold, np.uint8(255), np.uint8(0))


def rot90(rgb: np.ndarray, k) -> np.ndarray:
    """90度回転。"""
    assert 0 <= k <= 3
    if k == 1:
        rgb = np.swapaxes(rgb, 0, 1)[::-1, :, :]
    elif k == 2:
        rgb = rgb[::-1, ::-1, :]
    elif k == 3:
        rgb = np.swapaxes(rgb, 0, 1)[:, ::-1, :]
    return rgb


@_float_to_uint8
def equalize(rgb: np.ndarray) -> np.ndarray:
    """ヒストグラム平坦化。"""
    import cv2
    gray = np.mean(rgb, axis=-1, keepdims=True, dtype=np.float32)
    eq = np.expand_dims(cv2.equalizeHist(gray.astype(np.uint8)), axis=-1)
    return rgb + (eq - gray)


@_float_to_uint8
def auto_contrast(rgb: np.ndarray, scale=255) -> np.ndarray:
    """オートコントラスト。"""
    gray = np.mean(rgb, axis=-1)
    b, w = gray.min(), gray.max()
    if b < w:
        rgb = (rgb - b) * (scale / (w - b))
    return rgb


@_float_to_uint8
def posterize(rgb: np.ndarray, bits) -> np.ndarray:
    """ポスタリゼーション。"""
    assert bits in range(1, 8 + 1)
    t = 2 ** (8 - bits) / 255
    return np.round(rgb * t) / t


def geometric_transform(rgb, width, height,
                        flip_h=False, flip_v=False,
                        degrees=0,
                        scale_h=1.0, scale_v=1.0, pos_h=0.5, pos_v=0.5,
                        interp='lanczos', border_mode='edge'):
    """cropや回転などをまとめて処理。

    Args:
        rgb: 入力画像
        width: 出力サイズ
        height: 出力サイズ
        flip_h: Trueなら水平に反転する。
        flip_v: Trueなら垂直に反転する。
        degrees: 回転する角度。(0や360なら回転無し。)
        scale_h: 水平方向のスケール。例えば0.5だと半分に縮小(zoom out / padding)、2.0だと倍に拡大(zoom in / crop)、1.0で等倍。
        scale_v: 垂直方向のスケール。例えば0.5だと半分に縮小(zoom out / padding)、2.0だと倍に拡大(zoom in / crop)、1.0で等倍。
        pos_h: スケール変換に伴う水平位置。0で左端、0.5で中央、1で右端。(0～1)
        pos_v: スケール変換に伴う垂直位置。0で上端、0.5で中央、1で下端。(0～1)

    Returns:
        rgb, m

        変換後画像と変換行列。

    """
    import cv2
    # 左上から時計回りに座標を用意
    src_points = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    dst_points = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    # 反転
    if flip_h:
        dst_points = dst_points[[1, 0, 3, 2]]
    if flip_v:
        dst_points = dst_points[[3, 2, 1, 0]]
    # 回転
    theta = degrees * np.pi * 2 / 360
    c, s = np.cos(theta), np.sin(theta)
    r = np.array([[c, -s], [s, c]], dtype=np.float32)
    src_points = np.dot(r, (src_points - 0.5).T).T + 0.5
    # スケール変換
    src_points[:, 0] /= scale_h
    src_points[:, 1] /= scale_v
    src_points[:, 0] -= (1 / scale_h - 1) * pos_h
    src_points[:, 1] -= (1 / scale_v - 1) * pos_v
    # 変換行列の作成
    src_points[:, 0] *= rgb.shape[1]
    src_points[:, 1] *= rgb.shape[0]
    dst_points[:, 0] *= width
    dst_points[:, 1] *= height
    m = cv2.getPerspectiveTransform(src_points, dst_points)
    # 画像の変換
    rgb = transform_image(rgb, width, height, m, interp=interp, border_mode=border_mode)
    return rgb, m


def transform_image(rgb, width, height, m, interp='lanczos', border_mode='edge'):
    """geometric_transformの画像変換処理部分。

    Args:
        rgb: 入力画像
        width: 出力サイズ
        height: 出力サイズ
        m: 変換行列。
        interp: 補間方法。'nearest', 'bilinear', 'bicubic', 'lanczos'。縮小時は自動的にcv2.INTER_AREA。
        border_mode: パディング方法。'edge', 'reflect', 'wrap'

    """
    import cv2
    cv2_interp = {
        'nearest': cv2.INTER_NEAREST,
        'bilinear': cv2.INTER_LINEAR,
        'bicubic': cv2.INTER_CUBIC,
        'lanczos': cv2.INTER_LANCZOS4,
    }[interp]
    cv2_border = {
        'edge': cv2.BORDER_REPLICATE,
        'reflect': cv2.BORDER_REFLECT_101,
        'wrap': cv2.BORDER_WRAP,
    }[border_mode]

    # 縮小ならINTER_AREA
    sh, sw = rgb.shape[:2]
    dr = transform_points([(0, 0), (sw, 0), (sw, sh), (0, sh)], m)
    dw = min(np.linalg.norm(dr[1] - dr[0]), np.linalg.norm(dr[2] - dr[3]))
    dh = min(np.linalg.norm(dr[3] - dr[0]), np.linalg.norm(dr[2] - dr[1]))
    if dw <= sw or dh <= sh:
        cv2_interp = cv2.INTER_AREA

    if rgb.shape[-1] in (1, 3):
        rgb = cv2.warpPerspective(rgb, m, (width, height), flags=cv2_interp, borderMode=cv2_border)
        if len(rgb.shape) == 2:
            rgb = np.expand_dims(rgb, axis=-1)
    else:
        resized_list = [cv2.warpPerspective(rgb[:, :, ch], m, (width, height), flags=cv2_interp, borderMode=cv2_border) for ch in range(rgb.shape[-1])]
        rgb = np.transpose(resized_list, (1, 2, 0))
    return rgb


def transform_points(points, m):
    """geometric_transformの座標変換。

    Args:
        points: 座標の配列。shape=(num_points, 2)。[(x, y)]
        m: 変換行列。

    Returns:
        変換後の座標の配列。

    """
    import cv2
    return cv2.perspectiveTransform(np.reshape(points, (-1, 1, 2)).astype(np.float32), m).reshape(-1, 2)


def erase_random(rgb, rand, bboxes=None, scale_low=0.02, scale_high=0.4, rate_1=1 / 3, rate_2=3, alpha=None, max_tries=30):
    """Random erasing <https://arxiv.org/abs/1708.04896>"""
    if bboxes is not None:
        bb_lt = bboxes[:, :2]  # 左上
        bb_rb = bboxes[:, 2:]  # 右下
        bb_lb = bboxes[:, (0, 3)]  # 左下
        bb_rt = bboxes[:, (1, 2)]  # 右上
        bb_c = (bb_lt + bb_rb) / 2  # 中央

    for _ in range(max_tries):
        s = rgb.shape[0] * rgb.shape[1] * rand.uniform(scale_low, scale_high)
        r = np.exp(rand.uniform(np.log(rate_1), np.log(rate_2)))
        ew = int(np.sqrt(s / r))
        eh = int(np.sqrt(s * r))
        if ew <= 0 or eh <= 0 or ew >= rgb.shape[1] or eh >= rgb.shape[0]:
            continue
        ex = rand.randint(0, rgb.shape[1] - ew)
        ey = rand.randint(0, rgb.shape[0] - eh)

        if bboxes is not None:
            box_lt = np.array([[ex, ey]])
            box_rb = np.array([[ex + ew, ey + eh]])
            # bboxの頂点および中央を1つでも含んでいたらNGとする
            if np.logical_and(box_lt <= bb_lt, bb_lt <= box_rb).all(axis=-1).any() or \
               np.logical_and(box_lt <= bb_rb, bb_rb <= box_rb).all(axis=-1).any() or \
               np.logical_and(box_lt <= bb_lb, bb_lb <= box_rb).all(axis=-1).any() or \
               np.logical_and(box_lt <= bb_rt, bb_rt <= box_rb).all(axis=-1).any() or \
               np.logical_and(box_lt <= bb_c, bb_c <= box_rb).all(axis=-1).any():
                continue
            # 面積チェック。塗りつぶされるのがbboxの面積の25%を超えていたらNGとする
            lt = np.maximum(bb_lt, box_lt)
            rb = np.minimum(bb_rb, box_rb)
            area_inter = np.prod(rb - lt, axis=-1) * (lt < rb).all(axis=-1)
            area_bb = np.prod(bb_rb - bb_lt, axis=-1)
            if (area_inter >= area_bb * 0.25).any():
                continue

        rgb = np.copy(rgb)
        rc = rand.randint(0, 256, size=rgb.shape[-1])
        if alpha:
            rgb[ey:ey + eh, ex:ex + ew, :] = (rgb[ey:ey + eh, ex:ex + ew, :] * (1 - alpha) + rc * alpha).astype(np.uint8)
        else:
            rgb[ey:ey + eh, ex:ex + ew, :] = rc[np.newaxis, np.newaxis, :]
        break

    return rgb


def mask_to_onehot(rgb, class_colors, append_bg=False):
    """RGBのマスク画像をone-hot形式に変換する。

    Args:
        class_colors: 色の配列。shape=(num_classes, 3)
        append_bg: class_colorsに該当しない色のクラスを追加するならTrue。

    Returns:
        ndarray shape=(H, W, num_classes) dtype=np.float32

        append_bgがTrueの場合はnum_classesはlen(class_colors) + 1

    """
    num_classes = len(class_colors) + (1 if append_bg else 0)
    result = np.zeros((rgb.shape[0], rgb.shape[1], num_classes), np.float32)
    for i in range(len(class_colors)):
        result[np.all(rgb == class_colors[i], axis=-1), i] = 1
    if append_bg:
        result[:, :, -1] = 1 - result[:, :, :-1].sum(axis=-1)
    return result


def mask_to_class(rgb, class_colors, void_class=-1):
    """RGBのマスク画像をクラスIDの配列に変換する。

    Args:
        class_colors: 色の配列。shape=(num_classes, 3)
        void_class: class_colorsに該当しない色のピクセルの値。

    Returns:
        ndarray shape=(H, W) dtype=np.int32

    """
    result = np.empty(rgb.shape[:2], dtype=np.int32)
    result[:] = void_class
    for i in range(len(class_colors)):
        result[np.all(rgb == class_colors[i], axis=-1)] = i
    return result


def class_to_mask(classes, class_colors):
    """クラスIDの配列をRGBのマスク画像に変換する。

    Args:
        classes: クラスIDの配列。 shape=(H, W)
        class_colors: 色の配列。shape=(num_classes, 3)

    Returns:
        ndarray shape=(H, W, 3)

    """
    return np.asarray(class_colors)[classes]


def dense_crf(rgb, pred,
              gaussian_sxy=(1, 1), gaussian_compat=3,
              bilateral_sxy=(4, 4), bilateral_srgb=(13, 13, 13), bilateral_compat=10,
              num_iter=5):
    """Dense CRF <https://github.com/lucasb-eyer/pydensecrf>

    Args:
        rgb: 入力画像。
        pred: 予測結果。shape=(height, width, num_classes) dtype=np.float32
        num_iter: 予測回数。

    Returns:
        ndarray shape=(height, width, num_classes) dtype=np.float32

    """
    import pydensecrf.densecrf as dcrf
    import pydensecrf.utils as du
    rgb = np.copy(rgb).astype(np.uint8)
    pred = pred.astype(np.float32)
    pred /= pred.sum(axis=-1, keepdims=True)

    if len(pred.shape) == 2:
        pred = np.expand_dims(pred, axis=-1)
    if pred.shape[-1] == 1:
        pred = np.concatenate([1 - pred, pred], axis=-1)  # 2クラスのsoftmaxみたいにする
    num_classes = pred.shape[-1]

    height, width = rgb.shape[:2]
    pred = resize(pred, width, height)
    U = pred.transpose(2, 0, 1).reshape((num_classes, -1))

    d = dcrf.DenseCRF2D(width, height, num_classes)
    d.setUnaryEnergy(np.ascontiguousarray(du.unary_from_softmax(U)))
    d.addPairwiseGaussian(sxy=gaussian_sxy, compat=gaussian_compat)
    d.addPairwiseBilateral(sxy=bilateral_sxy, srgb=bilateral_srgb, rgbim=rgb, compat=bilateral_compat)
    Q = d.inference(num_iter)
    MAP = np.array(Q, dtype=np.float32)

    if num_classes == 2:
        proba = MAP[1, ...].reshape((height, width, 1))
    else:
        proba = MAP.reshape((num_classes, height, width)).transpose(1, 2, 0)
    return proba
