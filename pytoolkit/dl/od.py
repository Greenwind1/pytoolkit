"""お手製Object detection。

https://github.com/ak110/object_detector
"""
import pathlib
import typing

import numpy as np

from . import callbacks as dl_callbacks, hvd, models, od_gen, od_net, od_pb
from .. import jsonex, log, ml, utils

# バージョン
_JSON_VERSION = '0.0.2'
# PASCAL VOC 07+12 trainvalで学習したときのmodel.json
_VOC_JSON_DATA = {
    "base_network": "vgg16",
    "input_size": [320, 320],
    "map_sizes": [40, 20, 10],
    "num_classes": 20,
    "pb_size_patterns": [
        [1.3966931104660034, 2.1220061779022217],
        [2.081390857696533, 5.119766712188721],
        [3.0007710456848145, 8.67410659790039],
        [5.763144016265869, 4.750326156616211],
        [4.065821170806885, 13.425251960754395],
        [10.922301292419434, 6.070690155029297],
        [7.031608581542969, 9.765619277954102],
        [3.765132427215576, 19.532089233398438]
    ],
    "version": "0.0.2",
}
# PASCAL VOC 07+12 trainvalで学習したときの重みファイル
_VOC_WEIGHTS_NAME = 'pytoolkit_od_voc.h5'
_VOC_WEIGHTS_URL = 'https://github.com/ak110/object_detector/releases/download/v0.0.1/model.h5'
_VOC_WEIGHTS_MD5 = '7adccff18e4e56cac3090da023b97afb'


class ObjectDetector(object):
    """モデル。

    候補として最初に準備するboxの集合を持つ。
    """

    def __init__(self, base_network, input_size, map_sizes, num_classes):
        self.base_network = base_network
        self.pb = od_pb.PriorBoxes(input_size, map_sizes, num_classes)
        self.model: models.Model = None

    def save(self, path: typing.Union[str, pathlib.Path]):
        """保存。"""
        data = {
            'version': _JSON_VERSION,
            'base_network': self.base_network,
            'input_size': self.pb.input_size,
            'map_sizes': self.pb.map_sizes,
            'num_classes': self.pb.num_classes,
        }
        data.update(self.pb.to_dict())
        jsonex.dump(data, path)

    @staticmethod
    def load(path: typing.Union[str, pathlib.Path]):
        """読み込み。(ファイル)"""
        return ObjectDetector.loads(jsonex.load(path))

    @staticmethod
    def loads(data: dict):
        """読み込み。(dict)"""
        if data['version'] == '0.0.1':
            data.update(data.pop('pb'))
        od = ObjectDetector(
            base_network=data['base_network'],
            input_size=data['input_size'],
            map_sizes=data['map_sizes'],
            num_classes=data['num_classes'])
        od.pb.from_dict(data)
        return od

    @staticmethod
    def load_voc(batch_size, strict_nms=True, use_multi_gpu=True):
        """PASCAL VOC 07+12 trainvalで学習済みのモデルを読み込む。

        # 引数
        - batch_size: 予測時のバッチサイズ。
        - strict_nms: クラスによらずNon-maximum suppressionするならTrue。(mAPは下がるが、重複したワクが出ないので実用上は良いはず)
        - use_multi_gpu: 予測をマルチGPUで行うならTrue。

        """
        od = ObjectDetector.loads(_VOC_JSON_DATA)
        od.load_weights(weights='voc', batch_size=batch_size,
                        strict_nms=strict_nms, use_multi_gpu=use_multi_gpu)
        return od

    def fit(self, X_train: [pathlib.Path], y_train: [ml.ObjectsAnnotation],
            X_val: [pathlib.Path], y_val: [ml.ObjectsAnnotation],
            batch_size, epochs, lr_scale=1, initial_weights='voc', pb_size_pattern_count=8,
            flip_h=True, flip_v=False, rotate90=False,
            plot_path=None, history_path=None):
        """学習。

        # 引数
        - lr_scale: 学習率を調整するときの係数
        - initial_weights: 重みの初期値。
                           Noneなら何も読まない。
                           'imagenet'ならバックボーンのみ。
                           'voc'ならPASCAL VOC 07+12 trainvalで学習済みのもの。
                           ファイルパスならそれを読む。
        - pb_size_pattern_count: Prior boxのサイズ・アスペクト比のパターンの種類数。
        - flip_h: Data augmentationで水平flipを行うか否か。
        - flip_v: Data augmentationで垂直flipを行うか否か。
        - rotate90: Data augmentationで0, 90, 180, 270度の回転を行うか否か。
        - plot_path: ネットワークの図を出力するならそのパス。拡張子はpngやsvgなど。
        - history_path: lossなどをtsvファイルに出力するならそのパス。
        """
        assert self.model is None
        # 訓練データに合わせたprior boxの作成
        if hvd.is_master():
            logger = log.get(__name__)
            logger.info(f'base network:         {self.base_network}')
            self.pb.fit(y_train, pb_size_pattern_count)
            pb_dict = self.pb.to_dict()
        else:
            pb_dict = None
        pb_dict = hvd.bcast(pb_dict)
        self.pb.from_dict(pb_dict)
        # prior boxのチェック
        if hvd.is_master():
            self.pb.summary()
            self.pb.check_prior_boxes(y_val)
        hvd.barrier()
        # モデルの作成
        self._create_model(mode='train', weights=initial_weights, batch_size=batch_size,
                           lr_scale=lr_scale, flip_h=flip_h, flip_v=flip_v, rotate90=rotate90)
        if plot_path:
            self.model.plot(plot_path)
        # 学習
        callbacks = []
        callbacks.append(dl_callbacks.learning_rate(reduce_epoch_rates=(0.5, 0.75, 0.875)))
        callbacks.extend(self.model.horovod_callbacks())
        if history_path:
            callbacks.append(dl_callbacks.tsv_logger(history_path))
        callbacks.append(dl_callbacks.epoch_logger())
        callbacks.append(dl_callbacks.freeze_bn(0.95))
        self.model.fit(X_train, y_train, validation_data=(X_val, y_val),
                       epochs=epochs, callbacks=callbacks)

    def save_weights(self, path: typing.Union[str, pathlib.Path]):
        """重みの保存。(学習後用)"""
        assert self.model is not None
        self.model.save(path)

    def load_weights(self, weights: typing.Union[str, pathlib.Path], batch_size, strict_nms=True, use_multi_gpu=True):
        """重みの読み込み。(予測用)

        # 引数
        - weights: 読み込む重み。'voc'ならVOC07+12で学習したものを読み込む。pathlib.Pathならそのまま読み込む。
        - batch_size: 予測時のバッチサイズ。
        - strict_nms: クラスによらずNon-maximum suppressionするならTrue。(mAPは下がるが、重複したワクが出ないので実用上は良いはず)
        - use_multi_gpu: 予測をマルチGPUで行うならTrue。

        """
        assert self.model is None
        self._create_model(mode='predict', weights=weights, batch_size=batch_size,
                           lr_scale=None, flip_h=False, flip_v=False, rotate90=False, strict_nms=strict_nms)
        # マルチGPU化。
        if use_multi_gpu:
            gpus = utils.get_gpu_count()
            self.model.set_multi_gpu_model(gpus)
        else:
            gpus = 1
        # 1回予測して計算グラフを構築
        self.model.model.predict_on_batch(np.zeros((gpus,) + self.pb.input_size + (3,), np.float32))

    def predict(self, X, conf_threshold=0.1, verbose=1) -> [ml.ObjectsPrediction]:
        """予測。"""
        assert self.model is not None
        pred = []
        seq = self.model.gen.flow(X, batch_size=self.model.batch_size)
        with utils.tqdm(total=len(X), unit='f', desc='predict', disable=verbose == 0) as pbar:
            for i, X_batch in enumerate(seq):
                # 予測
                pred_list = self.model.model.predict_on_batch(X_batch)
                # 整形：キャストしたりマスクしたり
                for p in pred_list:
                    pred_classes = p[:, 0].astype(np.int32)
                    pred_confs = p[:, 1]
                    pred_locs = p[:, 2:]
                    mask = pred_confs >= conf_threshold
                    pred.append(ml.ObjectsPrediction(pred_classes[mask], pred_confs[mask], pred_locs[mask, :]))
                # 次へ
                pbar.update(len(X_batch))
                if i + 1 >= len(seq):
                    assert i + 1 == len(seq)
                    break
        return pred

    @log.trace()
    def _create_model(self, mode, weights, batch_size, lr_scale, flip_h, flip_v, rotate90, strict_nms=None):
        """学習とか予測とか用に`tk.dl.models.Model`を作成して返す。

        # 引数
        - mode: 'pretrain', 'train', 'predict'のいずれか。(出力などが違う)
        - weights: 読み込む重み。Noneなら読み込まない。'imagenet'ならバックボーンだけ。'voc'ならVOC07+12で学習したものを読み込む。その他str, pathlib.Pathならそのまま読み込む。

        """
        logger = log.get(__name__)

        network, lr_multipliers = od_net.create_network(
            base_network=self.base_network, pb=self.pb,
            mode=mode, strict_nms=strict_nms)
        pi = od_net.get_preprocess_input(self.base_network)
        if mode == 'pretrain':
            gen = od_gen.create_pretrain_generator(self.pb.input_size, pi)
        else:
            gen = od_gen.create_generator(self.pb.input_size, pi, self.pb.encode_truth,
                                          flip_h=flip_h, flip_v=flip_v, rotate90=rotate90)
        self.model = models.Model(network, gen, batch_size)
        if mode in ('pretrain', 'train'):
            self.model.summary()

        if weights is None:
            logger.info(f'cold start.')
        elif weights == 'imagenet':
            logger.info(f'cold start with imagenet weights.')
        elif weights == 'voc':
            import keras
            if hvd.is_local_master():
                keras.utils.get_file(_VOC_WEIGHTS_NAME, _VOC_WEIGHTS_URL, file_hash=_VOC_WEIGHTS_MD5, cache_subdir='models')
            hvd.barrier()
            weights_path = keras.utils.get_file(_VOC_WEIGHTS_NAME, _VOC_WEIGHTS_URL, file_hash=_VOC_WEIGHTS_MD5, cache_subdir='models')
            weights_path = pathlib.Path(weights_path)
            self.model.load_weights(weights_path)
            logger.info(f'{weights_path.name} loaded.')
        else:
            self.model.load_weights(weights)
            if mode == 'predict':
                logger.info(f'{weights.name} loaded.')
            else:
                logger.info(f'warm start: {weights.name}')

        if mode == 'pretrain':
            # 事前学習：通常の分類としてコンパイル
            self.model.compile(sgd_lr=0.5 / 256, loss='categorical_crossentropy', metrics=['acc'])
        elif mode == 'train':
            # Object detectionとしてコンパイル
            assert lr_scale is not None
            sgd_lr = lr_scale * 0.5 / 256 / 3  # lossが複雑なので微調整
            self.model.compile(sgd_lr=sgd_lr, lr_multipliers=lr_multipliers, loss=self.pb.loss, metrics=self.pb.metrics)
        else:
            assert mode == 'predict'
            assert lr_scale is None
