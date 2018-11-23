#!/usr/bin/env python3
"""実験用コード。"""
import argparse
import pathlib

import numpy as np

import pytoolkit as tk


def _main():
    tk.better_exceptions()
    parser = argparse.ArgumentParser()
    parser.add_argument('--result-dir', default=pathlib.Path('results_cifar100'), type=pathlib.Path)
    parser.add_argument('--epochs', default=300, type=int)
    parser.add_argument('--batch-size', default=64, type=int)
    args = parser.parse_args()
    args.result_dir.mkdir(parents=True, exist_ok=True)
    with tk.dl.session(use_horovod=True):
        tk.log.init(args.result_dir / 'train.log')
        _run(args)


@tk.log.trace()
def _run(args):
    import keras

    (X_train, y_train), (X_val, y_val) = keras.datasets.cifar100.load_data()
    y_train = np.squeeze(y_train)
    y_val = np.squeeze(y_val)
    input_shape = X_train.shape[1:]
    num_classes = len(np.unique(y_train))

    with tk.log.trace_scope('create network'):
        builder = tk.dl.networks.Builder()
        x = inp = keras.layers.Input(input_shape)
        x = builder.conv2d(128, use_act=False, name=f'start')(x)
        for stage, filters in enumerate([128, 256, 512]):
            name1 = f'stage{stage + 1}'
            x = builder.conv2d(filters, strides=1 if stage == 0 else 2, use_act=False, name=f'{name1}_ds')(x)
            for block in range(8):
                name2 = f'stage{stage + 1}_block{block + 1}'
                sc = x
                x = builder.conv2d(filters // 4, name=f'{name2}_c1')(x)
                for d in range(7):
                    t = builder.conv2d(filters // 4, name=f'{name2}_d{d}')(x)
                    x = keras.layers.concatenate([x, t], name=f'{name2}_d{d}_cat')
                x = builder.conv2d(filters, 1, use_act=False, name=f'{name2}_c2')(x)
                x = keras.layers.add([sc, x], name=f'{name2}_add')
            x = builder.bn_act(name=f'{name1}')(x)
        x = keras.layers.Dropout(0.5, name='dropout')(x)
        x = keras.layers.GlobalAveragePooling2D(name='pooling')(x)
        x = builder.dense(num_classes, activation='softmax', name='predictions')(x)
        model = keras.models.Model(inputs=inp, outputs=x)

    gen = tk.image.ImageDataGenerator()
    gen.add(tk.image.Padding(probability=1))
    gen.add(tk.image.RandomRotate(probability=0.25))
    gen.add(tk.image.RandomCrop(probability=1))
    gen.add(tk.image.Resize(input_shape[:2]))
    gen.add(tk.image.RandomFlipLR(probability=0.5))
    gen.add(tk.image.RandomColorAugmentors())
    gen.add(tk.image.RandomErasing(probability=0.5))
    gen.add(tk.image.Preprocess(mode='tf'))
    gen.add(tk.generator.ProcessOutput(tk.ml.to_categorical(num_classes), batch_axis=True))

    model = tk.dl.models.Model(model, gen, args.batch_size)
    model.compile(sgd_lr=1e-3, loss='categorical_crossentropy', metrics=['acc'])
    model.summary()

    model.fit(X_train, y_train, validation_data=(X_val, y_val),
              epochs=args.epochs, tsv_log_path=args.result_dir / 'history.tsv',
              mixup=True, cosine_annealing=True)
    model.save(args.result_dir / 'model.h5')
    if tk.dl.hvd.is_master():
        proba_val = model.predict(X_val)
        tk.ml.print_classification_metrics(y_val, proba_val)


if __name__ == '__main__':
    _main()