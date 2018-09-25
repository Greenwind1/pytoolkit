"""画像分類の転移学習周りを簡単にまとめたコード。"""
import pathlib
import typing

import numpy as np

from . import hvd, models
from .. import applications, generator, image, jsonex, log, ml


class ImageClassifier(models.Model):
    """画像分類モデル。"""

    @classmethod
    def create(cls, class_names, network_type, input_size, batch_size, rotation_type):
        """学習用インスタンスの作成。"""
        assert len(class_names) >= 2
        assert network_type in ('resnet50', 'xception', 'nasnet_large')
        assert batch_size >= 1
        assert rotation_type in ('none', 'mirror', 'rotation', 'all')
        network, preprocess_mode = _create_network(len(class_names), network_type, (input_size, input_size))
        gen = _create_generator(len(class_names), (input_size, input_size), preprocess_mode, rotation_type)
        return cls(class_names, network_type, preprocess_mode, input_size, rotation_type, network, gen, batch_size)

    @classmethod
    def load(cls, filepath: typing.Union[str, pathlib.Path], batch_size):  # pylint: disable=W0221
        """予測用インスタンスの作成。"""
        filepath = pathlib.Path(filepath)
        # メタデータの読み込み
        metadata = jsonex.load(filepath.with_suffix('.json'))
        class_names = metadata['class_names']
        network_type = metadata.get('network_type', None)
        preprocess_mode = metadata['preprocess_mode']
        input_size = int(metadata.get('input_size', 256))
        rotation_type = metadata.get('rotation_type', 'none')
        gen = _create_generator(len(class_names), (input_size, input_size), preprocess_mode, rotation_type)
        # モデルの読み込み
        network = models.load_model(filepath, compile=False)
        # 1回予測して計算グラフを構築
        network.predict_on_batch(np.zeros((1, input_size, input_size, 3)))
        logger = log.get(__name__)
        logger.info('trainable params: %d', models.count_trainable_params(network))
        return cls(class_names, network_type, preprocess_mode, input_size, rotation_type, network, gen, batch_size)

    def __init__(self, class_names, network_type, preprocess_mode, input_size, rotation_type, network, gen, batch_size, postprocess=None):
        super().__init__(network, gen, batch_size, postprocess=postprocess)
        self.class_names = class_names
        self.network_type = network_type
        self.preprocess_mode = preprocess_mode
        self.input_size = input_size
        self.rotation_type = rotation_type

    def save(self, filepath: typing.Union[str, pathlib.Path], overwrite=True, include_optimizer=True):
        """保存。"""
        filepath = pathlib.Path(filepath)
        # メタデータの保存
        if hvd.is_master():
            metadata = {
                'class_names': self.class_names,
                'network_type': self.network_type,
                'preprocess_mode': self.preprocess_mode,
                'input_size': self.input_size,
                'rotation_type': self.rotation_type,
            }
            jsonex.dump(metadata, filepath.with_suffix('.json'))
        # モデルの保存
        super().save(filepath, overwrite=overwrite, include_optimizer=include_optimizer)


def _create_network(num_classes, network_type, image_size):
    """ネットワークを作って返す。"""
    import keras
    if network_type == 'vgg':
        base_model = applications.vgg16bn.vgg16bn(include_top=False, input_shape=(None, None, 3))
        preprocess_mode = 'caffe'
    elif network_type == 'resnet50':
        base_model = keras.applications.ResNet50(include_top=False, input_shape=(None, None, 3))
        preprocess_mode = 'caffe'
    elif network_type == 'xception':
        base_model = keras.applications.Xception(include_top=False, input_shape=(None, None, 3))
        preprocess_mode = 'tf'
    elif network_type == 'nasnet_large':
        base_model = keras.applications.NASNetLarge(include_top=False, input_shape=image_size + (3,))
        preprocess_mode = 'tf'
    else:
        raise ValueError(f'Invalid network type: {network_type}')
    x = base_model.outputs[0]
    x = keras.layers.GlobalAveragePooling2D()(x)
    x = keras.layers.Dense(num_classes, activation='softmax',
                           kernel_initializer='zeros',
                           kernel_regularizer=keras.regularizers.l2(1e-4),
                           name=f'pred_{num_classes}')(x)
    model = keras.models.Model(base_model.inputs, x)
    return model, preprocess_mode


def _create_generator(num_classes, image_size, preprocess_mode, rotation_type):
    """Generatorを作って返す。"""
    gen = image.ImageDataGenerator()
    gen.add(image.Resize(image_size))
    gen.add(image.Padding(probability=1))
    if rotation_type in ('rotation', 'all'):
        gen.add(image.RandomRotate(probability=0.25, degrees=180))
    else:
        gen.add(image.RandomRotate(probability=0.25))
    gen.add(image.RandomCrop(probability=1))
    gen.add(image.Resize(image_size))
    if rotation_type in ('mirror', 'all'):
        gen.add(image.RandomFlipLR(probability=0.5))
    gen.add(image.RandomColorAugmentors())
    gen.add(image.RandomErasing(probability=0.5))
    gen.add(image.Preprocess(mode=preprocess_mode))
    gen.add(generator.ProcessOutput(ml.to_categorical(num_classes), batch_axis=True))
    return gen