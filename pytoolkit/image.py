"""画像処理関連"""
import pathlib
import warnings

import numpy as np

from . import generator, ml, ndimage


class ImageDataGenerator(generator.Generator):
    """画像データのgenerator。

    Xは画像のファイルパスの配列またはndarray。
    ndarrayの場合は、(BGRではなく)RGB形式で、samples×rows×cols×channels。

    # 引数
    - grayscale: グレースケールで読み込むならTrue、RGBならFalse

    # 使用例
    ```
    gen = tk.image.ImageDataGenerator()
    gen.add(tk.image.ProcessOutput(tk.ml.to_categorical(num_classes), batch_axis=True))
    gen.add(tk.image.Resize((300, 300)))
    gen.add(tk.image.Mixup(probability=1, num_classes=num_classes))
    gen.add(tk.image.RandomPadding(probability=1))
    gen.add(tk.image.RandomRotate(probability=0.5))
    gen.add(tk.image.RandomCrop(probability=1))
    gen.add(tk.image.Resize((300, 300)))
    gen.add(tk.image.RandomFlipLR(probability=0.5))
    gen.add(tk.image.RandomColorAugmentors(probability=0.5))
    gen.add(tk.image.RandomErasing(probability=0.5))
    gen.add(tk.image.ProcessInput(tk.image.preprocess_input_abs1))
    ```

    """

    def __init__(self, grayscale=False, profile=False):
        super().__init__(profile=profile)
        self.add(LoadImage(grayscale))


def preprocess_input_mean(x: np.ndarray):
    """RGBそれぞれ平均値(定数)を引き算。

    `keras.applications.imagenet_utils.preprocess_input` のようなもの。(ただし `channels_last` 限定)
    `keras.applications`のVGG16/VGG19/ResNet50で使われる。
    """
    # 'RGB'->'BGR'
    x = x[..., ::-1]
    # Zero-center by mean pixel
    x[..., 0] -= 103.939
    x[..., 1] -= 116.779
    x[..., 2] -= 123.68
    return x


def preprocess_input_abs1(x: np.ndarray):
    """0～255を-1～1に変換。

    `keras.applications`のInceptionV3/Xceptionで使われる。
    """
    x /= 127.5
    x -= 1
    return x


def unpreprocess_input_abs1(x: np.ndarray):
    """`preprocess_input_abs1`の逆変換。"""
    x += 1
    x *= 127.5
    return x


class LoadImage(generator.Operator):
    """画像のリサイズ。

    # 引数

    - grayscale: グレースケールで読み込むならTrue、RGBならFalse
    """

    def __init__(self, grayscale):
        self.grayscale = grayscale

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        """処理。"""
        assert rand is not None  # noqa
        if isinstance(x, np.ndarray):
            # ndarrayならそのまま画像扱い
            x = np.copy(x).astype(np.float32)
        else:
            # ファイルパスなら読み込み
            assert isinstance(x, (str, pathlib.Path))
            x = ndimage.load(x, self.grayscale)
        assert len(x.shape) == 3
        assert x.shape[-1] == (1 if self.grayscale else 3)
        return x, y, w


class Resize(generator.Operator):
    """画像のリサイズ。

    # 引数

    - image_size: (height, width)のタプル
    - padding: アスペクト比を保持するためにパディングするならパディングの種類

    """

    def __init__(self, image_size, padding=None):
        self.image_size = image_size
        self.padding = padding
        assert len(self.image_size) == 2

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        """処理。"""
        assert rand is not None  # noqa
        x = ndimage.resize(x, self.image_size[1], self.image_size[0], padding=self.padding)
        return x, y, w


class ProcessInput(generator.Operator):
    """画像に対する任意の処理。

    # 引数

    func: 画像のndarrayを受け取り、処理結果を返す関数
    batch_axis: Trueの場合、funcに渡されるndarrayのshapeが(1, height, width, channels)になる。Falseなら(height, width, channels)。

    # 例1
    ```py
    gen.add(ProcessInput(tk.image.preprocess_input_abs1))
    ```

    # 例2
    ```py
    gen.add(ProcessInput(tk.image.preprocess_input_mean))
    ```

    # 例3
    ```py
    gen.add(ProcessInput(keras.applications.vgg16.preprocess_input, batch_axis=True))
    ```
    """

    def __init__(self, func, batch_axis=False):
        self.func = func
        self.batch_axis = batch_axis

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        """処理。"""
        assert rand is not None  # noqa
        if self.batch_axis:
            x = np.expand_dims(x, axis=0)
            x = self.func(x)
            x = np.squeeze(x, axis=0)
        else:
            x = self.func(x)
        return x, y, w


class ProcessOutput(generator.Operator):
    """ラベルに対する任意の処理。"""

    def __init__(self, func, batch_axis=False):
        self.func = func
        self.batch_axis = batch_axis

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        """処理。"""
        assert rand is not None  # noqa
        if y is not None:
            if self.batch_axis:
                y = np.expand_dims(y, axis=0)
                y = self.func(y)
                y = np.squeeze(y, axis=0)
            else:
                y = self.func(y)
        return x, y, w


class RandomPadding(generator.Operator):
    """パディング。

    この後のRandomCropを前提に、パディングするサイズは固定。
    パディングのやり方がランダム。
    """

    def __init__(self, probability=1, padding_rate=0.25):
        assert 0 < probability <= 1
        self.probability = probability
        self.padding_rate = padding_rate

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            padding = rand.choice(('edge', 'zero', 'one', 'rand'))
            padded_w = int(np.ceil(x.shape[1] * (1 + self.padding_rate)))
            padded_h = int(np.ceil(x.shape[0] * (1 + self.padding_rate)))
            x = ndimage.pad(x, padded_w, padded_h, padding, rand)
        return x, y, w


class RandomRotate(generator.Operator):
    """回転。"""

    def __init__(self, probability=1, degrees=15):
        assert 0 < probability <= 1
        self.probability = probability
        self.degrees = degrees

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            x = ndimage.rotate(x, rand.uniform(-self.degrees, self.degrees))
        return x, y, w


class RandomCrop(generator.Operator):
    """切り抜き。

    # Padding+Cropの例
    padding_rate=0.25、crop_rate=0.2で32px四方の画像を処理すると、
    上下左右に4pxずつパディングした後に、32px四方を切り抜く処理になる。
    256px四方だと、32pxパディングで256px四方を切り抜く。
    """

    def __init__(self, probability=1, crop_rate=0.4, aspect_prob=0.5, aspect_rations=(3 / 4, 4 / 3)):
        assert 0 < probability <= 1
        self.probability = probability
        self.crop_rate = crop_rate
        self.aspect_prob = aspect_prob
        self.aspect_rations = aspect_rations

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            cr = rand.uniform(1 - self.crop_rate, 1)
            ar = np.sqrt(rand.choice(self.aspect_rations)) if rand.rand() <= self.aspect_prob else 1
            cropped_w = min(int(np.floor(x.shape[1] * cr * ar)), x.shape[1])
            cropped_h = min(int(np.floor(x.shape[0] * cr / ar)), x.shape[0])
            crop_x = rand.randint(0, x.shape[1] - cropped_w + 1)
            crop_y = rand.randint(0, x.shape[0] - cropped_h + 1)
            x = ndimage.crop(x, crop_x, crop_y, cropped_w, cropped_h)
        return x, y, w


class RandomAugmentors(generator.Operator):
    """順番と適用確率をランダムにDataAugmentationを行う。

    # 引数
    augmentors: Augmentorの配列
    clip_rgb: RGB値をnp.clip(x, 0, 255)するならTrue
    """

    def __init__(self, augmentors, probability=1, clip_rgb=True):
        assert 0 < probability <= 1
        self.probability = probability
        self.augmentors = augmentors
        self.clip_rgb = clip_rgb

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            augmentors = self.augmentors[:]
            rand.shuffle(augmentors)
            for a in augmentors:
                x, y, w = a.execute(x, y, w, rand, ctx)
                assert x.dtype == np.float32, f'dtype error: {a.__class__}'
            # 色が範囲外になっていたら補正(飽和)
            if self.clip_rgb:
                x = np.clip(x, 0, 255)
        return x, y, w


class RandomColorAugmentors(RandomAugmentors):
    """色関連のDataAugmentationをいくつかまとめたもの。"""

    def __init__(self, probability=1):
        argumentors = [
            RandomBlur(probability=probability),
            RandomUnsharpMask(probability=probability),
            GaussianNoise(probability=probability),
            RandomSaturation(probability=probability),
            RandomBrightness(probability=probability),
            RandomContrast(probability=probability),
            RandomHue(probability=probability),
        ]
        super().__init__(argumentors, probability=1, clip_rgb=True)


class RandomFlipLR(generator.Operator):
    """左右反転。(`tk.ml.ObjectsAnnotation`対応)"""

    def __init__(self, probability=1):
        assert 0 < probability <= 1
        self.probability = probability

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            x = ndimage.flip_lr(x)
            if y is not None and isinstance(y, ml.ObjectsAnnotation):
                y.bboxes[:, [0, 2]] = 1 - y.bboxes[:, [2, 0]]
        return x, y, w


class RandomFlipTB(generator.Operator):
    """上下反転。(`tk.ml.ObjectsAnnotation`対応)"""

    def __init__(self, probability=1):
        assert 0 < probability <= 1
        self.probability = probability

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            x = ndimage.flip_tb(x)
            if y is not None and isinstance(y, ml.ObjectsAnnotation):
                y.bboxes[:, [1, 3]] = 1 - y.bboxes[:, [3, 1]]
        return x, y, w


class RandomRotate90(generator.Operator):
    """90度/180度/270度回転。(`tk.ml.ObjectsAnnotation`対応)"""

    def __init__(self, probability=1):
        assert 0 < probability <= 1
        self.probability = probability

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            k = rand.randint(0, 4)

            if k == 1:
                x = np.swapaxes(x, 0, 1)[::-1, :, :]
            elif k == 2:
                x = x[::-1, ::-1, :]
            elif k == 3:
                x = np.swapaxes(x, 0, 1)[:, ::-1, :]

            if y is not None and isinstance(y, ml.ObjectsAnnotation):
                if k == 1:
                    y.bboxes = y.bboxes[:, [1, 0, 3, 2]]
                    y.bboxes[:, [1, 3]] = 1 - y.bboxes[:, [3, 1]]
                elif k == 2:
                    y.bboxes = 1 - y.bboxes[:, [2, 3, 0, 1]]
                elif k == 3:
                    y.bboxes = y.bboxes[:, [1, 0, 3, 2]]
                    y.bboxes[:, [0, 2]] = 1 - y.bboxes[:, [2, 0]]

        return x, y, w


class RandomBlur(generator.Operator):
    """ぼかし。"""

    def __init__(self, probability=1, radius=0.75):
        assert 0 < probability <= 1
        self.probability = probability
        self.radius = radius

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            x = ndimage.blur(x, self.radius * rand.rand())
        return x, y, w


class RandomUnsharpMask(generator.Operator):
    """シャープ化。"""

    def __init__(self, probability=1, sigma=0.5, min_alpha=1, max_alpha=2):
        assert 0 < probability <= 1
        self.probability = probability
        self.sigma = sigma
        self.min_alpha = min_alpha
        self.max_alpha = max_alpha

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            x = ndimage.unsharp_mask(x, self.sigma, rand.uniform(self.min_alpha, self.max_alpha))
        return x, y, w


class RandomMedian(generator.Operator):
    """メディアンフィルタ。"""

    def __init__(self, probability=1, sizes=(3,)):
        assert 0 < probability <= 1
        self.probability = probability
        self.sizes = sizes

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            x = ndimage.median(x, rand.choice(self.sizes))
        return x, y, w


class GaussianNoise(generator.Operator):
    """ガウシアンノイズ。"""

    def __init__(self, probability=1, scale=5):
        assert 0 < probability <= 1
        self.probability = probability
        self.scale = scale

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            x = ndimage.gaussian_noise(x, rand, self.scale)
        return x, y, w


class RandomBrightness(generator.Operator):
    """明度の変更。"""

    def __init__(self, probability=1, shift=32):
        assert 0 < probability <= 1
        self.probability = probability
        self.shift = shift

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            x = ndimage.brightness(x, rand.uniform(-self.shift, self.shift))
        return x, y, w


class RandomContrast(generator.Operator):
    """コントラストの変更。"""

    def __init__(self, probability=1, var=0.25):
        assert 0 < probability <= 1
        self.probability = probability
        self.var = var

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            x = ndimage.contrast(x, rand.uniform(1 - self.var, 1 + self.var))
        return x, y, w


class RandomSaturation(generator.Operator):
    """彩度の変更。"""

    def __init__(self, probability=1, var=0.5):
        assert 0 < probability <= 1
        self.probability = probability
        self.var = var

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            x = ndimage.saturation(x, rand.uniform(1 - self.var, 1 + self.var))
        return x, y, w


class RandomHue(generator.Operator):
    """色相の変更。"""

    def __init__(self, probability=1, var=1 / 16, shift=8):
        assert 0 < probability <= 1
        self.probability = probability
        self.var = var
        self.shift = shift

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            alpha = rand.uniform(1 - self.var, 1 + self.var, (3,))
            beta = rand.uniform(- self.shift, + self.shift, (3,))
            x = ndimage.hue_lite(x, alpha, beta)
        return x, y, w


class RandomErasing(generator.Operator):
    """Random Erasing。

    https://arxiv.org/abs/1708.04896

    # 引数
    - object_aware: yがObjectsAnnotationのとき、各オブジェクト内でRandom Erasing。(論文によるとTrueとFalseの両方をやるのが良い)
    - object_aware_prob: 各オブジェクト毎のRandom Erasing率。全体の確率は1.0にしてこちらで制御する。

    """

    def __init__(self, probability=1, scale_low=0.02, scale_high=0.4, rate_1=1 / 3, rate_2=3, object_aware=False, object_aware_prob=0.5, max_tries=30):
        assert 0 < probability <= 1
        assert scale_low <= scale_high
        assert rate_1 <= rate_2
        self.probability = probability
        self.scale_low = scale_low
        self.scale_high = scale_high
        self.rate_1 = rate_1
        self.rate_2 = rate_2
        self.object_aware = object_aware
        self.object_aware_prob = object_aware_prob
        self.max_tries = max_tries

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            bboxes = np.round(y.bboxes * np.array(x.shape)[[1, 0, 1, 0]]) if isinstance(y, ml.ObjectsAnnotation) else None
            if self.object_aware:
                assert bboxes is not None
                # bboxes同士の重なり判定
                inter = ml.is_intersection(bboxes, bboxes)
                inter[range(len(bboxes)), range(len(bboxes))] = False  # 自分同士は重なってないことにする
                # 各box内でrandom erasing。
                for i, b in enumerate(bboxes):
                    if (b[2:] - b[:2] <= 1).any():
                        warnings.warn(f'bboxサイズが不正: {y.filename}, {b}')
                        continue  # 安全装置：サイズが無いboxはskip
                    if rand.rand() <= self.object_aware_prob:
                        b = np.copy(b).astype(int)
                        # box内に含まれる他のboxを考慮
                        inter_boxes = np.copy(bboxes[inter[i]])
                        inter_boxes -= np.expand_dims(np.tile(b[:2], 2), axis=0)  # bに合わせて平行移動
                        # random erasing
                        x[b[1]:b[3], b[0]:b[2], :] = self._erase_random(x[b[1]:b[3], b[0]:b[2], :], rand, inter_boxes)
            else:
                # 画像全体でrandom erasing。
                x = self._erase_random(x, rand, bboxes)
        return x, y, w

    def _erase_random(self, x, rand, bboxes):
        if bboxes is not None:
            bb_lt = bboxes[:, :2]  # 左上
            bb_rb = bboxes[:, 2:]  # 右下
            bb_lb = bboxes[:, (0, 3)]  # 左下
            bb_rt = bboxes[:, (1, 2)]  # 右上
            bb_c = (bb_lt + bb_rb) / 2  # 中央

        for _ in range(self.max_tries):
            s = x.shape[0] * x.shape[1] * rand.uniform(self.scale_low, self.scale_high)
            r = np.exp(rand.uniform(np.log(self.rate_1), np.log(self.rate_2)))
            ew = int(np.sqrt(s / r))
            eh = int(np.sqrt(s * r))
            if ew <= 0 or eh <= 0 or ew >= x.shape[1] or eh >= x.shape[0]:
                continue
            ex = rand.randint(0, x.shape[1] - ew)
            ey = rand.randint(0, x.shape[0] - eh)

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

            x[ey:ey + eh, ex:ex + ew, :] = rand.randint(0, 255, size=3)[np.newaxis, np.newaxis, :]
            break

        return x


class Mixup(generator.Operator):
    """`mixup`

    yはone-hot化済みの前提

    - mixup: Beyond Empirical Risk Minimization
      https://arxiv.org/abs/1710.09412

    # 引数
    - alpha: α
    - beta: β
    - data_loader: X[i]と返すべきshapeを受け取り、データを読み込んで返す。
    - num_classes: クラス数 (指定した場合、one-hot化を行う)

    """

    def __init__(self, probability=1, alpha=0.2, beta=0.2, data_loader=None, num_classes=None):
        assert 0 < probability <= 1
        self.probability = probability
        self.alpha = alpha
        self.beta = beta
        self.data_loader = data_loader or self._load_data
        self.num_classes = num_classes

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            assert y is not None
            # 混ぜる先を選ぶ
            ti = rand.randint(0, ctx.data_count)
            x2 = self.data_loader(ctx.X[ti], x.shape)
            y2 = ctx.y[ti]
            if self.num_classes is not None:
                t = np.zeros((self.num_classes,), dtype=y.dtype)
                t[y2] = 1
                y2 = t
            assert x.shape == x2.shape
            assert y.shape == y2.shape
            # 混ぜる
            m = rand.beta(self.alpha, self.beta)
            assert 0 <= m <= 1
            x = x * m + x2 * (1 - m)
            y = y * m + y2 * (1 - m)
        return x, y, w

    def _load_data(self, x, shape):
        """画像の読み込み"""
        assert self is not None
        return ndimage.resize(ndimage.load(x), shape[1], shape[0])


class SamplewiseStandardize(generator.Operator):
    """標準化。0～255に適当に収める。"""

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        x = ndimage.standardize(x)
        return x, y, w


class ToGrayScale(generator.Operator):
    """グレースケール化。チャンネル数はとりあえず維持。"""

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        assert len(x.shape) == 3
        start_shape = x.shape
        x = ndimage.to_grayscale(x)
        x = np.tile(np.expand_dims(x, axis=-1), (1, 1, start_shape[-1]))
        assert x.shape == start_shape
        return x, y, w


class RandomBinarize(generator.Operator):
    """ランダム2値化(白黒化)。"""

    def __init__(self, threshold_min=128 - 32, threshold_max=128 + 32):
        assert 0 < threshold_min < 255
        assert 0 < threshold_max < 255
        assert threshold_min < threshold_max
        self.threshold_min = threshold_min
        self.threshold_max = threshold_max

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.data_augmentation:
            threshold = rand.uniform(self.threshold_min, self.threshold_max)
            x = ndimage.binarize(x, threshold)
        else:
            x = ndimage.binarize(x, (self.threshold_min + self.threshold_max) / 2)
        return x, y, w


class RotationsLearning(generator.Operator):
    """画像を0,90,180,270度回転させた画像を与え、その回転を推定する学習。

    Unsupervised Representation Learning by Predicting Image Rotations
    https://arxiv.org/abs/1803.07728

    # 使い方

    - `y` は `np.zeros((len(X),))` とする。
    - 4クラス分類として学習する。
    - 一番最後に `gen.add(tk.image.RotationsLearning())`

    """

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        assert y == 0
        k = rand.randint(0, 4)
        x = ndimage.rot90(x, k)
        y = np.zeros((4,))
        y[k] = 1
        return x, y, w


class CustomOperator(generator.Operator):
    """カスタム処理用。"""

    def __init__(self, process):
        self.process = process

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        x, y, w = self.process(x, y, w, rand, ctx)
        return x, y, w


class CustomAugmentation(generator.Operator):
    """カスタム処理用。"""

    def __init__(self, process, probability=1):
        assert 0 < probability <= 1
        self.process = process
        self.probability = probability

    def execute(self, x, y, w, rand, ctx: generator.GeneratorContext):
        if ctx.do_augmentation(rand, self.probability):
            x, y, w = self.process(x, y, w, rand, ctx)
        return x, y, w
