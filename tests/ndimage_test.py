import pathlib

import numpy as np

import pytoolkit as tk

_BASE_DIR = pathlib.Path(__file__).resolve().parent


def test_saveload_alpha(tmpdir):
    img = tk.ndimage.load(_BASE_DIR / 'data' / 'Alpha.png')
    assert img.shape[-1] == 3
    tk.ndimage.save(str(tmpdir.join('output.png')), img)


def test_saveload_grayscale(tmpdir):
    img = tk.ndimage.load(_BASE_DIR / 'data' / 'Lenna.png', grayscale=True)
    tk.ndimage.save(str(tmpdir.join('output.png')), img)


def test_filters():
    """画像の変換のテスト。目視したいので結果を`../___check/ndimage/`に保存しちゃう。"""
    save_dir = _BASE_DIR.parent / '___check' / 'ndimage'
    rand = np.random.RandomState(1234)
    filters = [
        (0, 'original', lambda rgb: rgb),
        (0, 'pad_edge', lambda rgb: tk.ndimage.pad(rgb, 300, 300, padding='edge')),
        (0, 'pad_zero', lambda rgb: tk.ndimage.pad(rgb, 300, 300, padding='zero')),
        (0, 'pad_half', lambda rgb: tk.ndimage.pad(rgb, 300, 300, padding='half')),
        (0, 'pad_mean', lambda rgb: tk.ndimage.pad(rgb, 300, 300, padding='mean')),
        (0, 'pad_one', lambda rgb: tk.ndimage.pad(rgb, 300, 300, padding='one')),
        (0, 'pad_refl', lambda rgb: tk.ndimage.pad(rgb, 300, 300, padding='reflect')),
        (0, 'pad_wrap', lambda rgb: tk.ndimage.pad(rgb, 300, 300, padding='wrap')),
        (0, 'rotate', lambda rgb: tk.ndimage.rotate(rgb, +15, expand=False)),
        (0, 'rotate', lambda rgb: tk.ndimage.rotate(rgb, -15, expand=False)),
        (0, 'rotate', lambda rgb: tk.ndimage.rotate(rgb, +15, expand=True)),
        (0, 'rotate', lambda rgb: tk.ndimage.rotate(rgb, -15, expand=True)),
        (0, 'crop', lambda rgb: tk.ndimage.crop(rgb, 30, 30, 200, 200)),
        (0, 'flip_lr', tk.ndimage.flip_lr),
        (0, 'flip_tb', tk.ndimage.flip_tb),
        (0, 'resize', lambda rgb: tk.ndimage.resize(rgb, 128, 64, padding='edge')),
        (0, 'resize', lambda rgb: tk.ndimage.resize(rgb, 128, 64, padding=None)),
        (1, 'gaussian_noise', lambda rgb: tk.ndimage.gaussian_noise(rgb, rand, 16)),
        (1, 'blur', lambda rgb: tk.ndimage.blur(rgb, 0.5)),
        (1, 'unsharp_mask', lambda rgb: tk.ndimage.unsharp_mask(rgb, 0.5, 1.5)),
        (1, 'median_3', lambda rgb: tk.ndimage.median(rgb, 3)),
        (1, 'brightness_n', lambda rgb: tk.ndimage.brightness(rgb, -32)),
        (1, 'brightness_p', lambda rgb: tk.ndimage.brightness(rgb, 32)),
        (1, 'saturation_l', lambda rgb: tk.ndimage.saturation(rgb, 0.5)),
        (1, 'saturation_h', lambda rgb: tk.ndimage.saturation(rgb, 1.5)),
        (1, 'contrast_l', lambda rgb: tk.ndimage.contrast(rgb, 0.75)),
        (1, 'contrast_h', lambda rgb: tk.ndimage.contrast(rgb, 1.25)),
        (1, 'hue_lite_b', lambda rgb: tk.ndimage.hue_lite(rgb, np.array([0.95, 0.95, 1.05]), np.array([-8, -8, +8]))),
        (1, 'hue_lite_g', lambda rgb: tk.ndimage.hue_lite(rgb, np.array([0.95, 1.05, 0.95]), np.array([-8, +8, -8]))),
        (1, 'hue_lite_r', lambda rgb: tk.ndimage.hue_lite(rgb, np.array([1.05, 0.95, 0.95]), np.array([+8, -8, -8]))),
        (1, 'standardize', tk.ndimage.standardize),
        (1, 'equalize', tk.ndimage.equalize),
        (1, 'auto_contrast', tk.ndimage.auto_contrast),
        (1, 'posterize4', lambda rgb: tk.ndimage.posterize(rgb, 4)),
        (1, 'posterize5', lambda rgb: tk.ndimage.posterize(rgb, 5)),
        (1, 'posterize6', lambda rgb: tk.ndimage.posterize(rgb, 6)),
        (1, 'posterize7', lambda rgb: tk.ndimage.posterize(rgb, 7)),
        (1, 'posterize8', lambda rgb: tk.ndimage.posterize(rgb, 8)),
        (1, 'binarize_1', lambda rgb: tk.ndimage.binarize(rgb, 128 - 32)),
        (1, 'binarize_2', lambda rgb: tk.ndimage.binarize(rgb, 128 + 32)),
        (0, 'rot90', lambda rgb: tk.ndimage.rot90(rgb, 1)),
        (0, 'rot180', lambda rgb: tk.ndimage.rot90(rgb, 2)),
        (0, 'rot270', lambda rgb: tk.ndimage.rot90(rgb, 3)),
    ]

    rgb = tk.ndimage.load(_BASE_DIR / 'data' / 'Lenna.png')  # 256x256の某有名画像
    save_dir.mkdir(parents=True, exist_ok=True)
    for cp in save_dir.iterdir():
        cp.unlink()
    for i, (partial, name, filter_func) in enumerate(filters):
        x = np.copy(rgb)
        t = filter_func(x[64:-64, 64:-64, :] if partial else x)

        assert t.dtype == np.float32
        assert len(t.shape) == 3

        if partial:
            x[64:-64, 64:-64, :] = t
        else:
            x = t
        tk.ndimage.save(save_dir / f'{i:02d}_{name}.png', x)
